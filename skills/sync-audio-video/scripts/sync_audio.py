#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "scipy"]
# ///
"""Sync an externally recorded audio track (WAV etc.) to a video.

Finds the offset by cross-correlating the video's own (scratch/camera) audio
against the external track, checks for clock drift, muxes the external audio
onto the video (video stream copied, not re-encoded), then re-correlates the
result to verify it lands at 0.

Offset convention: external-audio time t plays at video time t + offset.
  offset > 0  -> external audio is delayed (adelay)
  offset < 0  -> external audio's head is trimmed (atrim)

Usage:
  uv run sync_audio.py VIDEO AUDIO [-o OUT] [--analyze-only] [--fix-drift]
"""
import argparse, os, subprocess, sys, tempfile
import numpy as np
from scipy.signal import correlate


def decode(path, sr, stream="a:0"):
    """Decode one audio stream to mono float32 at `sr` via ffmpeg."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-map", f"0:{stream}", "-vn",
         "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True, check=True).stdout
    x = np.frombuffer(out, np.float32).astype(np.float64)
    if x.size == 0:
        sys.exit(f"error: no audio decoded from {path}")
    return (x - x.mean()) / (x.std() + 1e-9)


def offset(video_a, ext, sr, start=0):
    """Offset (s) of ext relative to video_a[start:], plus a confidence ratio."""
    c = np.abs(correlate(video_a, ext, mode="full", method="fft"))
    i = int(np.argmax(c))
    lag = i - (len(ext) - 1)
    conf = c[i] / (np.median(c) + 1e-12)
    return (start + lag) / sr, conf


def overlap(d, vdur, edur):
    """Video-time span where both tracks have audio, given offset d."""
    return max(0.0, d), min(vdur, d + edur)


def windowed_offsets(video_a, ext, sr, lo, hi):
    """Offset in an early and a late window of the overlap [lo, hi], for drift.

    Windows must stay inside the overlap: outside it the video audio has no
    counterpart in ext and the correlation peak is noise."""
    span = hi - lo
    win = min(20.0, span / 4)
    res = []
    for frac in (0.1, 0.75):
        s = int((lo + span * frac) * sr)
        seg = video_a[s:s + int(win * sr)]
        if len(seg) < sr:  # too short to say anything
            return None
        d, conf = offset(seg, ext, sr, start=s)
        res.append((s / sr, d, conf))
    return res


def probe_duration(path):
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True, check=True).stdout)


def analyze(video, audio, sr, label=""):
    va, ea = decode(video, sr), decode(audio, sr)
    d, conf = offset(va, ea, sr)
    print(f"{label}offset={d:+.4f}s  confidence={conf:.0f}x")
    w = windowed_offsets(va, ea, sr, *overlap(d, len(va) / sr, len(ea) / sr))
    drift = None
    if w:
        (t0, d0, c0), (t1, d1, c1) = w
        # (drift_s, span_s, offset extrapolated to video t=0)
        drift = (d1 - d0, t1 - t0, d0 - (d1 - d0) / (t1 - t0) * t0)
        print(f"{label}  @{t0:6.1f}s offset={d0:+.4f}s (conf {c0:.0f}x)")
        print(f"{label}  @{t1:6.1f}s offset={d1:+.4f}s (conf {c1:.0f}x)")
        print(f"{label}  drift={drift[0]*1000:+.1f}ms over {drift[1]:.0f}s")
        # Drift smears the whole-track peak, so a repeated musical phrase can
        # win instead. If the windows agree with each other but not with the
        # whole-track result, trust the windows.
        if abs(d1 - d0) < 0.5 and abs(d - (d0 + d1) / 2) > 0.05:
            print(f"{label}warning: whole-track offset disagrees with windows; "
                  f"using window estimate {drift[2]:+.4f}s", file=sys.stderr)
            d, conf = drift[2], min(c0, c1)
        if abs(drift[0]) > 0.02:
            print(f"{label}note: drift exceeds half a frame — consider --fix-drift",
                  file=sys.stderr)
    return d, conf, drift, len(va) / sr, len(ea) / sr


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video")
    p.add_argument("audio")
    p.add_argument("-o", "--out", help="default: '<video> synced.<ext>'")
    p.add_argument("--analyze-only", action="store_true",
                   help="print offset/drift and exit, no output file")
    p.add_argument("--offset", type=float,
                   help="skip analysis and use this offset (seconds)")
    p.add_argument("--fix-drift", action="store_true",
                   help="resample external audio to cancel measured drift")
    p.add_argument("--trim-to-audio", action="store_true",
                   help="cut the video to start/end exactly where the external "
                        "audio does (re-encodes video)")
    p.add_argument("--keep-camera-audio", action="store_true",
                   help="also keep the original camera audio as a 2nd track")
    p.add_argument("--sr", type=int, default=8000,
                   help="analysis sample rate (default 8000 = 0.125ms precision)")
    a = p.parse_args()

    if a.offset is not None:
        d, conf, drift = a.offset, None, None
        vdur, edur = probe_duration(a.video), probe_duration(a.audio)
    else:
        d, conf, drift, vdur, edur = analyze(a.video, a.audio, a.sr)
        if conf < 10:
            print("warning: low confidence (<10x) — the camera may not have "
                  "captured the same sound; check the result by ear/eye.",
                  file=sys.stderr)
    if a.analyze_only:
        return

    root, ext = os.path.splitext(a.video)
    out = a.out or f"{root} synced{ext}"
    is_mp4 = os.path.splitext(out)[1].lower() in (".mp4", ".m4v")
    acodec = ["-c:a", "aac", "-b:a", "320k"] if is_mp4 else ["-c:a", "pcm_s24le"]

    chain = []
    if a.fix_drift and drift and abs(drift[0]) > 0.001:
        # External clock runs (1+r) vs video; stretch to match.
        ratio = 1 + drift[0] / drift[1]
        sr_in = int(subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=sample_rate", "-of", "csv=p=0", a.audio],
            capture_output=True, text=True, check=True).stdout)
        chain.append(f"asetrate={sr_in / ratio:.4f},aresample={sr_in}")
        d = drift[2]
        edur *= ratio
        print(f"drift correction: speed ratio {1/ratio:.7f}, start offset {d:+.4f}s")
    lo, hi = overlap(d, vdur, edur)
    # In trim mode the output starts at video time lo, so the audio needs no
    # delay when d >= 0; otherwise align it to video t=0 as usual.
    shift = d - lo if a.trim_to_audio else d
    if shift > 0:
        chain.append(f"adelay={shift*1000:.2f}:all=1")
    elif shift < 0:
        chain.append(f"atrim=start={-shift:.4f},asetpts=PTS-STARTPTS")
    chain.append("apad")
    fc = f"[1:a]{','.join(chain)}[a]"
    vmap, vcodec, tail = "0:v:0", ["-c:v", "copy"], ["-shortest"]
    if a.trim_to_audio:
        # Frame-accurate cut needs a re-encode; video frames snap to the
        # next frame boundary (< 1 frame), audio keeps its first transient.
        fc += f";[0:v]trim=start={lo:.4f}:end={hi:.4f},setpts=PTS-STARTPTS[v]"
        vmap = "[v]"
        vcodec = ["-c:v", "libx264", "-crf", "14", "-preset", "slow",
                  "-pix_fmt", "yuv420p"]
        tail = ["-t", f"{hi - lo:.4f}"]
        print(f"trim: video {lo:.4f}s -> {hi:.4f}s ({hi - lo:.3f}s)")

    cmd = ["ffmpeg", "-v", "error", "-y", "-i", a.video, "-i", a.audio,
           "-filter_complex", fc, "-map", vmap, "-map", "[a]"]
    if a.keep_camera_audio:
        cmd += ["-map", "0:a:0"]
    cmd += [*vcodec, *acodec, *tail, out]
    print("$ " + " ".join(f"'{x}'" if " " in x or "'" in x else x for x in cmd))
    subprocess.run(cmd, check=True)

    # Verify: synced track vs original camera audio should now be ~0.
    va = decode(a.video, a.sr)
    sa = decode(out, a.sr)
    if a.trim_to_audio:  # compare against the same slice of camera audio
        va = va[int(lo * a.sr):int(hi * a.sr)]
        vlo, vhi = 0.0, hi - lo
    else:
        vlo, vhi = lo, hi
    v, vconf = offset(va, sa, a.sr)
    w = windowed_offsets(va, sa, a.sr, vlo, vhi)
    worst = max(abs(x[1]) for x in w) if w else abs(v)
    print(f"verify: whole-track={v*1000:+.1f}ms (conf {vconf:.0f}x)  "
          f"worst window={worst*1000:.1f}ms")
    fps_frame = 1 / 24
    print("OK" if worst < fps_frame / 2 else
          "WARNING: residual > half a frame — inspect manually or try --fix-drift")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

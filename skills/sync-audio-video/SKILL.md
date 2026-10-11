---
name: sync-audio-video
description: Sync an external audio recording (WAV) to a video
---

# Sync Audio to Video

Replace a video's camera/scratch audio with a separately recorded track
(DAW export, field recorder, board mix) aligned to the sample, by
cross-correlating the two waveforms. No clapper, no timeline, no re-encode of
the video.

## When to Use

- "Line up / sync / align this WAV with this video"
- Replacing phone or camera audio with a mixer, recorder, or DAW export
- Live sets, DJ mixes, band recordings, interviews with a separate mic
- Requires the video to have *some* audio of the same event, even quiet or
  distorted. With no audio on the camera, waveform matching can't work.

## Procedure

1. Probe both files (`ffprobe -show_entries format=duration:stream=codec_type,sample_rate`)
   to confirm the video has an audio stream and the durations are plausible.
2. Run the bundled script (needs `ffmpeg` + `uv`):

   ```bash
   uv run scripts/sync_audio.py VIDEO AUDIO [-o OUT]
   ```

   It finds the offset, checks drift in an early and a late window, muxes
   (video `-c copy`; audio PCM 24-bit for .mov/.mkv, AAC 320k for .mp4), then
   re-correlates the output against the original camera audio and prints `OK`
   when the worst-window residual is under half a frame.
   Default output: `<video> synced.<ext>` next to the video.
3. Useful flags:
   - `--analyze-only` — just report offset/confidence/drift.
   - `--fix-drift` — resample the external audio to cancel clock drift
     (use when drift > ~20ms, i.e. half a 24fps frame; common for >10-min
     recordings from separate devices).
   - `--keep-camera-audio` — keep the original audio as a second track.
   - `--offset S` — skip analysis and use a known offset.
4. Report to the user: the offset (and direction), confidence, drift, the
   verify result, and the output path.

## Pitfalls

- **Low confidence (<10x)**: the camera likely didn't capture the same
  sound, or the clips don't overlap. Don't trust the result; say so.
- **Whole-track vs windowed disagreement**: with drift, the whole-track peak
  smears and a repeated musical phrase can win (seen: +7.8s vs true +0.44s).
  The script detects this and uses the windowed estimate. Mention it if it
  fires.
- **Negative offset** (the recording started before the video): handled by
  trimming the external track's head, not by delaying the video.
- **Inverted polarity** is common (negative correlation peak) and harmless;
  the script uses |correlation|.
- **Very long files** (>1h): analysis at 8kHz needs ~1-2 GB RAM for the FFT;
  pass `--sr 4000` if memory is tight (precision drops to 0.25ms, still
  far below one frame).
- If the external audio is much longer than the video (whole set vs one
  clip), that's fine: output is trimmed to the video length.

## Verification

The script verifies itself. Trust the `worst window` figure, not the
whole-track one, which can be fooled by drift. Under ~20ms is
frame-accurate. For extra assurance, scrub to a visible transient (hand
clap, drum hit) in the output.

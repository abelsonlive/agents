#!/usr/bin/env python3
"""Fetch Spotify playlist tracklists with no API key (stdlib only).

Usage:
  spotify_playlist.py <playlist-url-or-id> [...]          # print "Artist - Title" lines
  spotify_playlist.py --json <url-or-id> [...]            # JSON: [{id,name,tracks:[{title,artist,uri}]}]

Source: https://open.spotify.com/embed/playlist/<id> embeds a __NEXT_DATA__ JSON blob.
Limit: the embed returns at most 100 tracks per playlist. A result of exactly 100
means the playlist is probably truncated.
"""
import json
import re
import sys
import urllib.request

UA = "Mozilla/5.0"


def playlist_id(s):
    m = re.search(r"playlist[/:]([A-Za-z0-9]{22})", s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{22}", s):
        return s
    raise ValueError(f"cannot parse playlist id from {s!r}")


def fetch(pid):
    req = urllib.request.Request(
        f"https://open.spotify.com/embed/playlist/{pid}", headers={"User-Agent": UA}
    )
    html = urllib.request.urlopen(req, timeout=30).read().decode()
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S
    )
    if not m:
        raise RuntimeError("no __NEXT_DATA__ in embed page (private playlist or layout change)")
    ent = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    tracks = [
        {
            "title": t["title"],
            "artist": t["subtitle"].replace("\xa0", " "),
            "uri": t["uri"],
        }
        for t in ent["trackList"]
    ]
    return {"id": pid, "name": ent.get("name"), "tracks": tracks, "truncated": len(tracks) >= 100}


def main(argv):
    as_json = "--json" in argv
    args = [a for a in argv if a != "--json"]
    if not args:
        print(__doc__)
        return 1
    res = [fetch(playlist_id(a)) for a in args]
    if as_json:
        print(json.dumps(res, indent=1, ensure_ascii=False))
    else:
        for r in res:
            flag = "  [TRUNCATED at 100]" if r["truncated"] else ""
            print(f"# {r['name']} ({len(r['tracks'])}){flag}")
            for t in r["tracks"]:
                print(f"{t['artist']} - {t['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

---
name: spotify-playlist-tracks
description: Use when given a Spotify playlist link and you need its tracklist. No API key; uses the public embed page.
---

# Spotify playlist tracks (no API key)

`open.spotify.com/embed/playlist/<id>` embeds the tracklist as JSON in a
`<script id="__NEXT_DATA__">` tag. No key, login, or OAuth. Verified 2026-10-27.

## Use

```bash
python3 scripts/spotify_playlist.py <url-or-id> [...]          # Artist - Title lines
python3 scripts/spotify_playlist.py --json <url-or-id> [...]   # structured
```

Accepts full share URLs (`?si=...` ignored), `spotify:playlist:` URIs, or bare 22-char ids.
Fields per track: `title`, `artist` (comma-joined, `subtitle` in the source), `uri`.
Title keeps remix info (`Foreal - Seb Zito Remix`); artist is the credited artists.

## Limits

- **Max 100 tracks per playlist.** Exactly 100 = probably truncated. The embed exposes no total count.
- No album, ISRC, or release year in the embed.
- Private/deleted playlists have no `__NEXT_DATA__` entity; the script raises.
- Dead ends (don't retry): `open.spotify.com/get_access_token` is 403 (Varnish "URL Blocked"); the public playlist page gives only an og:description and a few `music:song` tags.
- Full lists past 100 need the official Web API (client-credentials app token), which requires a Spotify developer app.

## Downstream

Pair with `slsk-download` (search bare `artist title`, no separators) to fetch files via slskd.

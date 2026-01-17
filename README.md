# SpotAPI Python Client

This is a tiny, runnable Python client built on top of [Aran404/SpotAPI](https://github.com/Aran404/SpotAPI).

Features:
- Public search (no login)
- Read public playlist info (no login)
- Create playlist and add songs using cookie-based login (no CAPTCHA solver required)
- Export playlist tracks (JSON/CSV)
- **Download playlist audio from YouTube** using Spotify metadata + yt-dlp (tags + cover art embedded)

## Setup

1) Install Python 3.10+ and pip.
2) Install dependencies:

```bash
pip install -r requirements.txt
```

If you prefer, you can install directly:

```bash
pip install spotapi pymongo redis websockets yt-dlp
```

## Cookie-based login (recommended)
SpotAPI supports loading a logged-in session from your browser cookies to avoid third-party CAPTCHA solvers.

1) Log in to https://open.spotify.com in your browser.
2) Export your cookies as a JSON map (name->value). Tools like browser devtools or extensions can help.
3) Create a JSON file with the following structure (see `cookies_template.json`):

```json
{
  "identifier": "your_email_or_username",
  "cookies": {
    "sp_dc": "...",
    "sp_key": "..."
  }
}
```

4) Use `--cookies path\to\cookies.json` with authenticated commands below.

Note: See the SpotAPI README "Import Cookies" section for details.

## Commands

- Public search:
```bash
python spot_client.py search --query "weezer" --limit 5
```

- Public playlist info:
```bash
python spot_client.py public-playlist --playlist 37i9dQZF1DXcBWIGoYBM5M --limit 10
```

- Create a playlist (auth via cookies):
```bash
python spot_client.py create-playlist --name "SpotAPI Demo" --cookies .\\cookies.json
```

- Add a song to a playlist (auth via cookies):
```bash
# by song URL/URI/ID
python spot_client.py add-to-playlist --playlist YOUR_PLAYLIST_ID --song-id https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC --cookies .\\cookies.json

# or by query (takes top result)
python spot_client.py add-to-playlist --playlist YOUR_PLAYLIST_ID --query "weezer buddy holly" --cookies .\\cookies.json
```

- Export playlist tracks (publicly accessible playlists):
```bash
python spot_client.py export-playlist --playlist 37i9dQZF1DXcBWIGoYBM5M --format json --output out.json

python spot_client.py export-playlist --playlist 37i9dQZF1DXcBWIGoYBM5M --format csv --output out.csv
```

- **Download playlist audio from YouTube** (using Spotify metadata):
```bash
python spot_client.py export-playlist-with-audio --playlist 37i9dQZF1DXcBWIGoYBM5M --output ./downloads --audio-format mp3
```
This command:
1. Fetches the playlist metadata from Spotify (track names, artists, albums).
2. Saves metadata to `downloads/metadata.json`.
3. Searches YouTube for each track using the query `"{track_name} {artist_name}"`.
4. Downloads the best audio quality available and converts to the specified format (mp3, m4a, opus, vorbis, wav).
5. Embeds title/artist/album tags and album art (when available) into mp3/m4a/opus/ogg outputs.
6. Saves all audio files to the output directory.
7. On failure, logs failed tracks to `downloads/failed.json`.

Format options: `mp3`, `m4a`, `opus`, `vorbis`, `wav` (default: `mp3`)

Tips:
- `--playlist` accepts a raw ID, a `spotify:playlist:...` URI, or a full open.spotify.com URL.
- `--song-id` accepts a raw ID, `spotify:track:...` URI, or a track URL.

## Legal & Responsibility

### Audio Download Disclaimer
**⚠️ Important:** This feature downloads audio from YouTube and is intended for **personal, non-commercial use only**. You are responsible for:

- **Copyright compliance**: Ensure you have the legal right to download content. Many songs are copyrighted.
- **YouTube's ToS**: Downloading from YouTube may violate their Terms of Service. Check their policies before use.
- **Local laws**: Audio downloading laws vary by jurisdiction. Comply with your local regulations.
- **Attribution**: If you share or distribute downloaded files, provide proper attribution to the original artists.

**This tool does not bypass copyright protections or DRM.** It simply automates finding and downloading publicly available content from YouTube. The author is not responsible for misuse.

### Spotify API Disclaimer
- This client depends on SpotAPI, which accesses Spotify's public and private endpoints. Use responsibly and review the repository's Legal Notice.
- Some private actions may change or break based on Spotify changes; consult SpotAPI docs if an endpoint behavior changes.

## Responsible Use

- Use this tool for **personal backups** of playlists you own or have the right to download.
- Respect artists' rights and support them through official channels (Spotify, streaming, concert tickets).
- Do not redistribute or commercialize downloaded content without permission.

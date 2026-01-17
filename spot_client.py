import argparse
import json
import os
import re
import sys
from typing import Any, Dict, Optional
import csv
import subprocess
import shutil
import glob
import requests
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, ID3NoHeaderError, TIT2, TPE1, TALB
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus

from spotapi import Song, PublicPlaylist, PrivatePlaylist, Login, Config, NoopLogger


def parse_track_id(s: str) -> str:
    # Accept raw ID, spotify:track:ID, or https://open.spotify.com/track/ID
    m = re.search(r"(?:(?:spotify:track:)|(?:open\.spotify\.com/track/))?([A-Za-z0-9]{10,})", s)
    if m:
        return m.group(1)
    return s


def print_song_results(data: Dict[str, Any]) -> None:
    items = data.get("data", {}).get("searchV2", {}).get("tracksV2", {}).get("items", [])
    for idx, item in enumerate(items):
        meta = item.get("item", {}).get("data", {})
        name = meta.get("name")
        uri = meta.get("uri")
        artists = ", ".join(a.get("profile", {}).get("name") for a in meta.get("artists", {}).get("items", []) if a.get("profile"))
        print(f"{idx:02d} | {name} — {artists} | {uri}")


def cmd_search(args: argparse.Namespace) -> int:
    song = Song()
    result = song.query_songs(args.query, limit=args.limit, offset=args.offset)
    print_song_results(result)
    return 0


def cmd_public_playlist(args: argparse.Namespace) -> int:
    pl = PublicPlaylist(args.playlist)
    info = pl.get_playlist_info(limit=args.limit, offset=args.offset)
    header = info.get("data", {}).get("playlistV2", {}).get("name") or "Playlist"
    print(f"{header}")
    # Try to print track summaries if present
    tracks = info.get("data", {}).get("playlistV2", {}).get("content", {}).get("items", [])
    for idx, entry in enumerate(tracks):
        track = entry.get("itemV2", {}).get("data", {})
        if not track:
            continue
        name = track.get("name")
        artists = ", ".join(a.get("profile", {}).get("name") for a in track.get("artists", {}).get("items", []) if a.get("profile"))
        uri = track.get("uri")
        print(f"{idx:02d} | {name} — {artists} | {uri}")
    return 0


def _extract_track_from_item(item: Dict[str, Any]) -> Dict[str, Any]:
    data = item.get("itemV2", {}).get("data", {})
    if not data:
        return {}
    name = data.get("name")
    uri = data.get("uri")
    # album name
    album_name = None
    album = data.get("albumOfTrack") or {}
    if isinstance(album, dict):
        album_name = album.get("name") or album.get("__typename")
        cover_art = album.get("coverArt", {}).get("sources", [])
        cover_url = cover_art[0].get("url") if cover_art else None
    else:
        cover_url = None
    # artists
    artists_items = data.get("artists", {}).get("items", [])
    artists = ", ".join(a.get("profile", {}).get("name") for a in artists_items if a.get("profile"))
    # duration (best-effort)
    duration_ms = None
    duration = data.get("duration") or {}
    if isinstance(duration, dict):
        duration_ms = duration.get("totalMilliseconds")
    # ID from URI if available
    track_id = None
    if isinstance(uri, str):
        m = re.search(r"track:([A-Za-z0-9]+)", uri)
        if m:
            track_id = m.group(1)
    return {
        "name": name,
        "artists": artists,
        "album": album_name,
        "uri": uri,
        "id": track_id,
        "duration_ms": duration_ms,
        "cover_url": cover_url,
    }


def _collect_playlist_tracks(pl: PublicPlaylist) -> list[Dict[str, Any]]:
    tracks: list[Dict[str, Any]] = []
    try:
        # Try pagination for full coverage
        for chunk in pl.paginate_playlist():
            items = chunk.get("data", {}).get("playlistV2", {}).get("content", {}).get("items", [])
            for entry in items:
                t = _extract_track_from_item(entry)
                if t:
                    tracks.append(t)
        if tracks:
            return tracks
    except Exception:
        pass
    
    # Fallback: fetch in batches with offset
    offset = 0
    limit = 100
    while True:
        try:
            info = pl.get_playlist_info(limit=limit, offset=offset)
            items = info.get("data", {}).get("playlistV2", {}).get("content", {}).get("items", [])
            if not items:
                break
            for entry in items:
                t = _extract_track_from_item(entry)
                if t:
                    tracks.append(t)
            if len(items) < limit:
                break
            offset += limit
        except Exception:
            break
    return tracks


def _download_cover(url: Optional[str]) -> Optional[bytes]:
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.content
    except Exception:
        return None
    return None


def _embed_tags(file_path: str, track: Dict[str, Any], cover_bytes: Optional[bytes]) -> None:
    ext = os.path.splitext(file_path)[1].lower()
    title = track.get("name") or ""
    artist = track.get("artists") or ""
    album = track.get("album") or ""

    if ext == ".mp3":
        try:
            audio = MP3(file_path)
            if audio.tags is None:
                audio.add_tags()
            audio.save()
        except ID3NoHeaderError:
            audio = MP3(file_path)
            audio.add_tags()
            audio.save()

        id3 = ID3(file_path)
        id3.setall("TIT2", [TIT2(encoding=3, text=title)])
        id3.setall("TPE1", [TPE1(encoding=3, text=artist)])
        id3.setall("TALB", [TALB(encoding=3, text=album)])
        if cover_bytes:
            id3.delall("APIC")
            id3.add(APIC(encoding=3, mime="image/jpeg", type=3, desc=u"Cover", data=cover_bytes))
        id3.save(v2_version=3)
        return

    if ext in {".m4a", ".mp4", ".aac"}:
        audio = MP4(file_path)
        audio["\xa9nam"] = [title]
        audio["\xa9ART"] = [artist]
        audio["\xa9alb"] = [album]
        if cover_bytes:
            fmt = MP4Cover.FORMAT_JPEG
            audio["covr"] = [MP4Cover(cover_bytes, imageformat=fmt)]
        audio.save()
        return

    if ext in {".opus"}:
        audio = OggOpus(file_path)
        audio["title"] = [title]
        audio["artist"] = [artist]
        audio["album"] = [album]
        audio.save()
        return

    if ext in {".ogg"}:
        audio = OggVorbis(file_path)
        audio["title"] = [title]
        audio["artist"] = [artist]
        audio["album"] = [album]
        audio.save()
        return

    # For wav or unsupported, skip tagging
    return


def cmd_export_playlist(args: argparse.Namespace) -> int:
    pl = PublicPlaylist(args.playlist)
    tracks = _collect_playlist_tracks(pl)
    if not tracks:
        print("No tracks found or playlist inaccessible.", file=sys.stderr)
        return 2
    out = args.output
    fmt = args.format.lower()
    if fmt == "json":
        with open(out, "w", encoding="utf-8") as f:
            json.dump(tracks, f, ensure_ascii=False, indent=2)
    elif fmt == "csv":
        fieldnames = ["name", "artists", "album", "uri", "id", "duration_ms"]
        with open(out, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in tracks:
                writer.writerow({k: row.get(k) for k in fieldnames})
    else:
        print("Unsupported format. Use json or csv.", file=sys.stderr)
        return 2
    print(f"Exported {len(tracks)} tracks to {out}")
    return 0


def build_cfg() -> Config:
    # Minimal config; you can extend with solver/proxy if desired
    return Config(logger=NoopLogger())


def load_login_from_cookies(path: str) -> Login:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Cookies file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        dump = json.load(f)
    cfg = build_cfg()
    return Login.from_cookies(dump, cfg)


def cmd_create_playlist(args: argparse.Namespace) -> int:
    login = load_login_from_cookies(args.cookies)
    priv = PrivatePlaylist(login)
    uri = priv.create_playlist(args.name)
    print(uri)
    return 0


def cmd_add_to_playlist(args: argparse.Namespace) -> int:
    login = load_login_from_cookies(args.cookies)
    priv = PrivatePlaylist(login, playlist=args.playlist)
    song_helper = Song(playlist=priv)

    song_id: Optional[str] = None
    if args.song_id:
        song_id = parse_track_id(args.song_id)
    elif args.query:
        search = Song()
        data = search.query_songs(args.query, limit=1)
        items = data.get("data", {}).get("searchV2", {}).get("tracksV2", {}).get("items", [])
        if not items:
            print("No results found for query.", file=sys.stderr)
            return 2
        uri = items[0].get("item", {}).get("data", {}).get("uri")
        if not uri:
            print("Top result missing URI.", file=sys.stderr)
            return 2
        song_id = parse_track_id(uri)
    else:
        print("Provide either --song-id or --query", file=sys.stderr)
        return 2

    song_helper.add_song_to_playlist(song_id)
    print("Added.")
    return 0


def cmd_export_playlist_with_audio(args: argparse.Namespace) -> int:
    # Check if yt-dlp is available
    if shutil.which("yt-dlp") is None:
        print("yt-dlp not found. Install it: pip install yt-dlp", file=sys.stderr)
        return 2
    
    # Collect playlist tracks from Spotify
    pl = PublicPlaylist(args.playlist)
    tracks = _collect_playlist_tracks(pl)
    if not tracks:
        print("No tracks found or playlist inaccessible.", file=sys.stderr)
        return 2
    
    # Create output directory
    out_dir = args.output
    os.makedirs(out_dir, exist_ok=True)
    
    # Export metadata to JSON
    meta_file = os.path.join(out_dir, "metadata.json")
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(tracks, f, ensure_ascii=False, indent=2)
    print(f"Metadata saved to {meta_file}")
    
    # Download audio from YouTube
    failed = []
    for idx, track in enumerate(tracks, 1):
        name = track.get("name")
        artists = track.get("artists")
        query = f"{name} {artists}".strip()
        cover_bytes = _download_cover(track.get("cover_url"))
        
        # Safe filename
        safe_name = re.sub(r'[<>:"/\\|?*]', '', f"{idx:03d}_{name}")[:100]
        out_file = os.path.join(out_dir, f"{safe_name}.%(ext)s")
        
        print(f"[{idx}/{len(tracks)}] Downloading: {query}")
        try:
            cmd = [
                "yt-dlp",
                "-f", "bestaudio/best",
                "--extract-audio",
                "--audio-format", args.audio_format,
                "--audio-quality", "192",
                "-o", out_file,
                f"ytsearch:{query}",
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            if result.returncode != 0:
                print(f"  ⚠ Failed: {query}", file=sys.stderr)
                failed.append((name, artists, "yt-dlp error"))
                continue

            # Find the actual downloaded file and embed tags
            pattern = out_file.replace("%(ext)s", "*")
            candidates = glob.glob(pattern)
            if not candidates:
                failed.append((name, artists, "file not found after download"))
                continue
            target_file = candidates[0]
            try:
                _embed_tags(target_file, track, cover_bytes)
            except Exception as e:
                print(f"  ⚠ Tagging failed for {target_file}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠ Error: {e}", file=sys.stderr)
            failed.append((name, artists, str(e)))
    
    print(f"\nDownload complete. {len(tracks) - len(failed)}/{len(tracks)} succeeded.")
    if failed:
        fail_file = os.path.join(out_dir, "failed.json")
        with open(fail_file, "w", encoding="utf-8") as f:
            json.dump([{"name": n, "artists": a, "reason": r} for n, a, r in failed], f, ensure_ascii=False, indent=2)
        print(f"Failed tracks: {fail_file}")
    
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SpotAPI Python Client")
    sub = p.add_subparsers(dest="command", required=True)

    # search
    sp = sub.add_parser("search", help="Search songs (public)")
    sp.add_argument("--query", required=True, help="Search query")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--offset", type=int, default=0)
    sp.set_defaults(func=cmd_search)

    # public-playlist
    pp = sub.add_parser("public-playlist", help="Fetch public playlist info")
    pp.add_argument("--playlist", required=True, help="Playlist ID or URL or URI")
    pp.add_argument("--limit", type=int, default=25)
    pp.add_argument("--offset", type=int, default=0)
    pp.set_defaults(func=cmd_public_playlist)

    # export-playlist (publicly accessible playlists)
    ep = sub.add_parser("export-playlist", help="Export playlist tracks to JSON/CSV")
    ep.add_argument("--playlist", required=True, help="Playlist ID or URL or URI")
    ep.add_argument("--format", choices=["json", "csv"], default="json")
    ep.add_argument("--output", required=True, help="Output file path")
    ep.set_defaults(func=cmd_export_playlist)

    # export-playlist-with-audio
    ea = sub.add_parser("export-playlist-with-audio", help="Export playlist metadata + download audio from YouTube")
    ea.add_argument("--playlist", required=True, help="Playlist ID or URL or URI")
    ea.add_argument("--output", required=True, help="Output directory for audio files and metadata")
    ea.add_argument("--audio-format", choices=["mp3", "m4a", "opus", "vorbis", "wav"], default="mp3")
    ea.set_defaults(func=cmd_export_playlist_with_audio)

    # create-playlist (auth via cookies)
    cp = sub.add_parser("create-playlist", help="Create a playlist (auth)")
    cp.add_argument("--name", required=True)
    cp.add_argument("--cookies", required=True, help="Path to cookies JSON dump")
    cp.set_defaults(func=cmd_create_playlist)

    # add-to-playlist (auth via cookies)
    ap = sub.add_parser("add-to-playlist", help="Add a song to a playlist (auth)")
    ap.add_argument("--playlist", required=True, help="Playlist ID or URL or URI")
    gid = ap.add_mutually_exclusive_group(required=True)
    gid.add_argument("--song-id", help="Song ID/URL/URI to add")
    gid.add_argument("--query", help="Search query to add top result")
    ap.add_argument("--cookies", required=True, help="Path to cookies JSON dump")
    ap.set_defaults(func=cmd_add_to_playlist)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

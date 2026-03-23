"""Fetch and embed album cover art for MP3 files using iTunes Search API.

Searches iTunes for cover art matching each MP3's artist and title (parsed
from the filename pattern "Artist - Title.mp3"), then downloads and embeds the
artwork directly into the file's ID3 tags.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import requests
from mediafile import MediaFile

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wma", ".wav"}
RATE_LIMIT_SECONDS = 0.3
MIN_IMAGE_SIZE = 1000  # bytes


def parse_filename(filepath: str) -> tuple[str, str] | None:
    """Extract artist and title from 'Artist - Title.ext' filename."""
    name = os.path.splitext(os.path.basename(filepath))[0]
    if " - " not in name:
        return None
    artist, title = name.split(" - ", 1)
    # Strip featuring info from artist for cleaner search
    for prefix in ["feat.", "ft.", "feat ", "ft "]:
        idx = artist.lower().find(prefix)
        if idx != -1:
            artist = artist[:idx].strip().rstrip(",")
    # Remove parenthetical/bracket suffixes from title for better search
    clean_title = title.split("(")[0].split("[")[0].strip()
    return artist.strip(), clean_title or title.strip()


def search_itunes(
    artist: str, title: str, resolution: int = 600
) -> str | None:
    """Search iTunes for cover art URL. Returns high-res image URL or None."""
    try:
        resp = requests.get(
            ITUNES_SEARCH_URL,
            params={
                "term": f"{artist} {title}",
                "entity": "song",
                "media": "music",
                "limit": 5,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    results = data.get("results", [])
    if not results:
        return None

    artist_lower = artist.lower()
    title_lower = title.lower()
    best = None

    for r in results:
        r_artist = r.get("artistName", "").lower()
        r_track = r.get("trackName", "").lower()
        art_url = r.get("artworkUrl100", "")
        if not art_url:
            continue
        art_url = art_url.replace("100x100bb", f"{resolution}x{resolution}bb")
        if artist_lower in r_artist or r_artist in artist_lower:
            if title_lower in r_track or r_track in title_lower:
                return art_url
            if best is None:
                best = art_url
        elif best is None:
            best = art_url

    return best


def has_embedded_art(filepath: str) -> bool:
    """Check if file already has embedded cover art."""
    try:
        mf = MediaFile(filepath)
        return mf.art is not None
    except Exception:
        return False


def embed_art(filepath: str, image_data: bytes) -> bool:
    """Embed cover art into audio file."""
    try:
        mf = MediaFile(filepath)
        mf.art = image_data
        mf.save()
        return True
    except Exception as e:
        print(f"    ERROR embedding: {e}")
        return False


def download_image(url: str) -> bytes | None:
    """Download image from URL."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        if len(resp.content) < MIN_IMAGE_SIZE:
            return None
        return resp.content
    except requests.RequestException:
        return None


def collect_audio_files(directory: str, recursive: bool = False) -> list[str]:
    """Collect supported audio files from directory."""
    files = []
    if recursive:
        for root, _, filenames in os.walk(directory):
            for f in filenames:
                if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS:
                    files.append(os.path.join(root, f))
    else:
        for f in os.listdir(directory):
            full = os.path.join(directory, f)
            if os.path.isfile(full) and os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS:
                files.append(full)
    return sorted(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch and embed album cover art for music files."
    )
    parser.add_argument(
        "directory",
        help="Path to directory containing music files",
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Show what would be done without downloading or embedding",
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Re-fetch art even if the file already has embedded art",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Search for music files recursively in subdirectories",
    )
    parser.add_argument(
        "-s", "--save-covers",
        metavar="DIR",
        help="Also save cover images to this directory",
    )
    parser.add_argument(
        "--resolution",
        type=int,
        default=600,
        help="Cover art resolution in pixels (default: 600)",
    )

    args = parser.parse_args(argv)

    if not os.path.isdir(args.directory):
        print(f"Error: '{args.directory}' is not a directory")
        return 1

    if args.save_covers:
        os.makedirs(args.save_covers, exist_ok=True)

    audio_files = collect_audio_files(args.directory, args.recursive)
    total = len(audio_files)
    print(f"Found {total} audio files")

    if total == 0:
        return 0

    found = 0
    skipped = 0
    failed = 0
    already_has_art = 0
    errors = 0

    for i, filepath in enumerate(audio_files, 1):
        parsed = parse_filename(filepath)
        if not parsed:
            print(f"[{i}/{total}] SKIP (can't parse): {os.path.basename(filepath)}")
            skipped += 1
            continue

        artist, title = parsed

        if not args.force and has_embedded_art(filepath):
            already_has_art += 1
            continue

        print(f"[{i}/{total}] {artist} - {title}")

        if args.dry_run:
            found += 1
            continue

        art_url = search_itunes(artist, title, args.resolution)
        if not art_url:
            print("    No cover found")
            failed += 1
            time.sleep(RATE_LIMIT_SECONDS)
            continue

        image_data = download_image(art_url)
        if not image_data:
            print("    Download failed")
            failed += 1
            time.sleep(RATE_LIMIT_SECONDS)
            continue

        if args.save_covers:
            safe_name = f"{artist} - {title}"[:80]
            for ch in '/\\:*?"<>|':
                safe_name = safe_name.replace(ch, "_")
            cover_path = os.path.join(args.save_covers, f"{safe_name}.jpg")
            with open(cover_path, "wb") as f:
                f.write(image_data)

        if embed_art(filepath, image_data):
            print(f"    OK ({len(image_data) // 1024}KB)")
            found += 1
        else:
            errors += 1

        time.sleep(RATE_LIMIT_SECONDS)

    print(f"\n{'=== DRY RUN ===' if args.dry_run else '=== DONE ==='}")
    print(f"  Already had art: {already_has_art}")
    print(f"  Covers fetched:  {found}")
    print(f"  Not found:       {failed}")
    print(f"  Errors:          {errors}")
    print(f"  Skipped:         {skipped}")
    print(f"  Total files:     {total}")

    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())

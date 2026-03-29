"""Fetch and embed album cover art for music files.

Searches multiple sources (Deezer, iTunes, MusicBrainz) for cover art matching
each file's artist and title (parsed from the filename pattern
"Artist - Title.mp3"), then downloads and embeds the artwork directly into the
file's metadata tags.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import unicodedata

import requests
from mediafile import MediaFile

SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wma", ".wav"}
RATE_LIMIT_SECONDS = 0.3
MIN_IMAGE_SIZE = 1000  # bytes


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """Normalize unicode characters for better search matching."""
    # Replace common unicode lookalikes with ASCII
    text = unicodedata.normalize("NFKD", text)
    # Remove combining characters but keep base letters
    return "".join(c for c in text if not unicodedata.combining(c))


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


def build_search_queries(artist: str, title: str) -> list[tuple[str, str]]:
    """Build multiple search query variations for better hit rate."""
    queries = [(artist, title)]

    # Try with normalized text (strips accents/special chars)
    norm_artist = normalize_text(artist)
    norm_title = normalize_text(title)
    if (norm_artist, norm_title) != (artist, title):
        queries.append((norm_artist, norm_title))

    # If artist has commas (multiple artists), try first artist only
    if "," in artist:
        first_artist = artist.split(",")[0].strip()
        queries.append((first_artist, title))

    # Strip "x" mashup separator
    if " x " in artist.lower() or " х " in artist.lower():
        first = re.split(r" [xх] ", artist, flags=re.IGNORECASE)[0].strip()
        queries.append((first, title))

    # Try artist-only search for very niche titles
    queries.append((artist, ""))

    return queries


# ---------------------------------------------------------------------------
# Cover art sources
# ---------------------------------------------------------------------------

def search_deezer(artist: str, title: str, resolution: int = 500) -> str | None:
    """Search Deezer API for cover art. Free, no API key needed."""
    query = f"{artist} {title}".strip()
    if not query:
        return None
    try:
        resp = requests.get(
            "https://api.deezer.com/search",
            params={"q": query, "limit": 5},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    results = data.get("data", [])
    if not results:
        return None

    artist_lower = artist.lower()
    title_lower = title.lower()
    best = None

    for r in results:
        r_artist = r.get("artist", {}).get("name", "").lower()
        r_track = r.get("title", "").lower()
        album = r.get("album", {})
        art_url = album.get("cover_xl") or album.get("cover_big") or album.get("cover_medium")
        if not art_url:
            continue
        if artist_lower in r_artist or r_artist in artist_lower:
            if title_lower in r_track or r_track in title_lower:
                return art_url
            if best is None:
                best = art_url
        elif best is None:
            best = art_url

    return best


def search_itunes(artist: str, title: str, resolution: int = 600) -> str | None:
    """Search iTunes for cover art URL."""
    query = f"{artist} {title}".strip()
    if not query:
        return None
    try:
        resp = requests.get(
            "https://itunes.apple.com/search",
            params={
                "term": query,
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


def search_musicbrainz(artist: str, title: str) -> str | None:
    """Search MusicBrainz for the recording, then fetch cover from Cover Art Archive."""
    query = f'artist:"{artist}" AND recording:"{title}"'
    try:
        resp = requests.get(
            "https://musicbrainz.org/ws/2/recording",
            params={"query": query, "limit": 5, "fmt": "json"},
            headers={"User-Agent": "MusicCoverFetcher/0.1.0 (github.com/MrDaila007/music-cover-fetcher)"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    recordings = data.get("recordings", [])
    for rec in recordings:
        for release in rec.get("releases", []):
            release_id = release.get("id")
            if not release_id:
                continue
            # Try Cover Art Archive
            try:
                caa_resp = requests.get(
                    f"https://coverartarchive.org/release/{release_id}/front-500",
                    timeout=10,
                    allow_redirects=True,
                )
                if caa_resp.status_code == 200 and len(caa_resp.content) > MIN_IMAGE_SIZE:
                    return caa_resp.url
            except requests.RequestException:
                continue

    return None


# Source registry: (name, function) in priority order
SOURCES = [
    ("Deezer", search_deezer),
    ("iTunes", search_itunes),
    ("MusicBrainz", search_musicbrainz),
]


def search_all_sources(
    artist: str, title: str, resolution: int = 600
) -> tuple[str | None, str]:
    """Try all sources with multiple query variations. Returns (url, source_name)."""
    queries = build_search_queries(artist, title)

    for source_name, search_fn in SOURCES:
        for q_artist, q_title in queries:
            if source_name == "MusicBrainz":
                art_url = search_fn(q_artist, q_title)
            else:
                art_url = search_fn(q_artist, q_title, resolution)
            if art_url:
                return art_url, source_name
            time.sleep(RATE_LIMIT_SECONDS)

    return None, ""


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------

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


def sanitize_filename(name: str) -> str:
    """Remove characters that are invalid in filenames."""
    for ch in '/\\:*?"<>|':
        name = name.replace(ch, "_")
    return name


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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
    parser.add_argument(
        "--sources",
        default="deezer,itunes,musicbrainz",
        help="Comma-separated list of sources to use (default: deezer,itunes,musicbrainz)",
    )

    args = parser.parse_args(argv)

    if not os.path.isdir(args.directory):
        print(f"Error: '{args.directory}' is not a directory")
        return 1

    # Filter sources based on --sources flag
    enabled = {s.strip().lower() for s in args.sources.split(",")}
    global SOURCES
    SOURCES = [(n, fn) for n, fn in SOURCES if n.lower() in enabled]
    if not SOURCES:
        print(f"Error: no valid sources in '{args.sources}'")
        print("Available: deezer, itunes, musicbrainz")
        return 1

    print(f"Sources: {', '.join(n for n, _ in SOURCES)}")

    if args.save_covers:
        os.makedirs(args.save_covers, exist_ok=True)

    audio_files = collect_audio_files(args.directory, args.recursive)
    total = len(audio_files)
    print(f"Found {total} audio files\n")

    if total == 0:
        return 0

    found = 0
    skipped = 0
    failed = 0
    already_has_art = 0
    errors = 0
    source_counts: dict[str, int] = {}

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

        art_url, source_name = search_all_sources(artist, title, args.resolution)
        if not art_url:
            print("    No cover found (all sources exhausted)")
            failed += 1
            continue

        image_data = download_image(art_url)
        if not image_data:
            print(f"    Download failed ({source_name})")
            failed += 1
            continue

        if args.save_covers:
            safe_name = sanitize_filename(f"{artist} - {title}"[:80])
            cover_path = os.path.join(args.save_covers, f"{safe_name}.jpg")
            with open(cover_path, "wb") as f:
                f.write(image_data)

        if embed_art(filepath, image_data):
            print(f"    OK via {source_name} ({len(image_data) // 1024}KB)")
            found += 1
            source_counts[source_name] = source_counts.get(source_name, 0) + 1
        else:
            errors += 1

    print(f"\n{'=== DRY RUN ===' if args.dry_run else '=== DONE ==='}")
    print(f"  Already had art: {already_has_art}")
    print(f"  Covers fetched:  {found}")
    if source_counts:
        for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
            print(f"    {src}: {cnt}")
    print(f"  Not found:       {failed}")
    print(f"  Errors:          {errors}")
    print(f"  Skipped:         {skipped}")
    print(f"  Total files:     {total}")

    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())

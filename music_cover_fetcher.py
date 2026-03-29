"""Fetch and embed album cover art and metadata for music files.

Searches multiple sources (Deezer, iTunes, MusicBrainz) for metadata matching
each file's artist and title (parsed from the filename pattern
"Artist - Title.mp3"), then downloads and embeds the artwork and tags directly
into the file's metadata.
"""

from __future__ import annotations

import argparse
import datetime
import json
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

# Metadata fields we work with (must match MediaFile attribute names)
META_FIELDS = [
    "title",
    "artist",
    "album",
    "albumartist",
    "genre",
    "year",
    "track",
    "tracktotal",
    "disc",
    "disctotal",
    "bpm",
    "isrc",
    "label",
]

# ---------------------------------------------------------------------------
# ANSI colors
# ---------------------------------------------------------------------------

_COLOR_SUPPORT: bool | None = None


def _supports_color() -> bool:
    global _COLOR_SUPPORT
    if _COLOR_SUPPORT is None:
        _COLOR_SUPPORT = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    return _COLOR_SUPPORT


def _c(code: str, text: str) -> str:
    if _supports_color():
        return f"\033[{code}m{text}\033[0m"
    return text


def green(text: str) -> str:
    return _c("32", text)


def yellow(text: str) -> str:
    return _c("33", text)


def red(text: str) -> str:
    return _c("31", text)


def dim(text: str) -> str:
    return _c("2", text)


def bold(text: str) -> str:
    return _c("1", text)


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    """Normalize unicode characters for better search matching."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def parse_filename(filepath: str) -> tuple[str, str] | None:
    """Extract artist and title from 'Artist - Title.ext' filename."""
    name = os.path.splitext(os.path.basename(filepath))[0]
    if " - " not in name:
        return None
    artist, title = name.split(" - ", 1)
    for prefix in ["feat.", "ft.", "feat ", "ft "]:
        idx = artist.lower().find(prefix)
        if idx != -1:
            artist = artist[:idx].strip().rstrip(",")
    clean_title = title.split("(")[0].split("[")[0].strip()
    return artist.strip(), clean_title or title.strip()


def build_search_queries(artist: str, title: str) -> list[tuple[str, str]]:
    """Build multiple search query variations for better hit rate."""
    queries = [(artist, title)]

    norm_artist = normalize_text(artist)
    norm_title = normalize_text(title)
    if (norm_artist, norm_title) != (artist, title):
        queries.append((norm_artist, norm_title))

    if "," in artist:
        first_artist = artist.split(",")[0].strip()
        queries.append((first_artist, title))

    if " x " in artist.lower() or " х " in artist.lower():
        first = re.split(r" [xх] ", artist, flags=re.IGNORECASE)[0].strip()
        queries.append((first, title))

    queries.append((artist, ""))
    return queries


# ---------------------------------------------------------------------------
# Metadata sources — each returns dict | None
# ---------------------------------------------------------------------------


def _match_score(artist: str, title: str, r_artist: str, r_title: str) -> int:
    """Score how well a result matches the query. Higher is better."""
    a = artist.lower()
    t = title.lower()
    ra = r_artist.lower()
    rt = r_title.lower()
    score = 0
    if a in ra or ra in a:
        score += 2
    if t and (t in rt or rt in t):
        score += 2
    return score


def search_deezer(artist: str, title: str, resolution: int = 500) -> dict | None:
    """Search Deezer API. Returns metadata dict or None."""
    query = f"{artist} {title}".strip()
    if not query:
        return None
    try:
        resp = requests.get(
            "https://api.deezer.com/search",
            params={"q": query, "limit": "5"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    results = data.get("data", [])
    if not results:
        return None

    best = None
    best_score = -1

    for r in results:
        r_artist = r.get("artist", {}).get("name", "")
        r_track = r.get("title", "")
        album = r.get("album", {})
        art_url = album.get("cover_xl") or album.get("cover_big") or album.get("cover_medium")

        score = _match_score(artist, title, r_artist, r_track)
        if score > best_score:
            best_score = score
            best = {
                "title": r_track or None,
                "artist": r_artist or None,
                "album": album.get("title") or None,
                "albumartist": None,
                "genre": None,  # Deezer /search doesn't return genre
                "year": None,  # Not in search results
                "track": r.get("track_position") or None,
                "tracktotal": None,
                "disc": r.get("disk_number") or None,
                "disctotal": None,
                "bpm": r.get("bpm") if r.get("bpm") else None,
                "isrc": r.get("isrc") or None,
                "label": None,
                "cover_url": art_url,
                "_source": "Deezer",
            }
            if score >= 4:  # Perfect match
                return best

    return best


def search_itunes(artist: str, title: str, resolution: int = 600) -> dict | None:
    """Search iTunes. Returns metadata dict or None."""
    query = f"{artist} {title}".strip()
    if not query:
        return None
    try:
        resp = requests.get(
            "https://itunes.apple.com/search",
            params={"term": query, "entity": "song", "media": "music", "limit": "5"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    results = data.get("results", [])
    if not results:
        return None

    best = None
    best_score = -1

    for r in results:
        r_artist = r.get("artistName", "")
        r_track = r.get("trackName", "")
        art_url = r.get("artworkUrl100", "")
        if art_url:
            art_url = art_url.replace("100x100bb", f"{resolution}x{resolution}bb")

        release_date = r.get("releaseDate", "")
        year = None
        if release_date and len(release_date) >= 4:
            try:
                year = int(release_date[:4])
            except ValueError:
                pass

        score = _match_score(artist, title, r_artist, r_track)
        if score > best_score:
            best_score = score
            best = {
                "title": r_track or None,
                "artist": r_artist or None,
                "album": r.get("collectionName") or None,
                "albumartist": None,
                "genre": r.get("primaryGenreName") or None,
                "year": year,
                "track": r.get("trackNumber") or None,
                "tracktotal": r.get("trackCount") or None,
                "disc": r.get("discNumber") or None,
                "disctotal": r.get("discCount") or None,
                "bpm": None,
                "isrc": None,
                "label": None,
                "cover_url": art_url or None,
                "_source": "iTunes",
            }
            if score >= 4:
                return best

    return best


def search_musicbrainz(artist: str, title: str, resolution: int = 0) -> dict | None:
    """Search MusicBrainz. Returns metadata dict or None."""
    query = f'artist:"{artist}" AND recording:"{title}"'
    try:
        resp = requests.get(
            "https://musicbrainz.org/ws/2/recording",
            params={"query": query, "limit": "5", "fmt": "json"},
            headers={"User-Agent": "MusicCoverFetcher/0.1.0 (github.com/MrDaila007/music-cover-fetcher)"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    recordings = data.get("recordings", [])
    for rec in recordings:
        # Extract artist from artist-credit
        credits = rec.get("artist-credit", [])
        rec_artist = credits[0].get("name", "") if credits else ""

        releases = rec.get("releases", [])
        if not releases:
            continue

        release = releases[0]
        release_id = release.get("id")

        # Parse year
        date_str = release.get("date", "")
        year = None
        if date_str and len(date_str) >= 4:
            try:
                year = int(date_str[:4])
            except ValueError:
                pass

        # ISRCs
        isrcs = rec.get("isrcs", [])

        # Try Cover Art Archive
        cover_url = None
        if release_id:
            try:
                caa_resp = requests.get(
                    f"https://coverartarchive.org/release/{release_id}/front-500",
                    timeout=10,
                    allow_redirects=True,
                )
                if caa_resp.status_code == 200 and len(caa_resp.content) > MIN_IMAGE_SIZE:
                    cover_url = caa_resp.url
            except requests.RequestException:
                pass

        return {
            "title": rec.get("title") or None,
            "artist": rec_artist or None,
            "album": release.get("title") or None,
            "albumartist": None,
            "genre": None,
            "year": year,
            "track": None,
            "tracktotal": None,
            "disc": None,
            "disctotal": None,
            "bpm": None,
            "isrc": isrcs[0] if isrcs else None,
            "label": None,
            "cover_url": cover_url,
            "_source": "MusicBrainz",
        }

    return None


# Source registry: (name, function) in priority order
SOURCES = [
    ("Deezer", search_deezer),
    ("iTunes", search_itunes),
    ("MusicBrainz", search_musicbrainz),
]


def search_all_sources(
    artist: str,
    title: str,
    resolution: int = 600,
    metadata_mode: bool = False,
) -> dict | None:
    """Try all sources with multiple query variations.

    Returns the best metadata dict, or None.
    In metadata_mode, prefer results with more filled fields.
    """
    queries = build_search_queries(artist, title)
    best_result: dict | None = None
    best_filled = -1

    for source_name, search_fn in SOURCES:
        for q_artist, q_title in queries:
            result = search_fn(q_artist, q_title, resolution)
            if result:
                if not metadata_mode:
                    return result
                # In metadata mode, prefer results with more data
                filled = sum(1 for k in META_FIELDS if result.get(k) is not None)
                if filled > best_filled:
                    best_filled = filled
                    best_result = result
                # If we have a very good result, stop early
                if filled >= len(META_FIELDS) - 2:
                    return best_result
            time.sleep(RATE_LIMIT_SECONDS)

    return best_result


# ---------------------------------------------------------------------------
# File metadata operations
# ---------------------------------------------------------------------------


def read_file_metadata(filepath: str) -> dict:
    """Read current metadata from audio file."""
    try:
        mf = MediaFile(filepath)
    except Exception:
        return {f: None for f in META_FIELDS + ["has_art"]}

    meta = {}
    for field in META_FIELDS:
        val = getattr(mf, field, None)
        # Treat empty strings as None
        if isinstance(val, str) and not val.strip():
            val = None
        # Treat 0 as empty for numeric fields (track, disc, bpm, etc.)
        if isinstance(val, (int, float)) and val == 0:
            val = None
        meta[field] = val
    meta["has_art"] = mf.art is not None
    return meta


def has_embedded_art(filepath: str) -> bool:
    """Check if file already has embedded cover art."""
    try:
        mf = MediaFile(filepath)
        return mf.art is not None
    except Exception:
        return False


def compute_changes(existing: dict, fetched: dict, force: bool = False) -> list[dict]:
    """Compare existing vs fetched metadata.

    Returns list of {field, current, proposed, action} dicts.
    action: 'fill' | 'overwrite' | 'match' | 'skip'
    """
    changes = []
    for field in META_FIELDS:
        current = existing.get(field)
        proposed = fetched.get(field)
        if proposed is None:
            action = "skip"
        elif current is None:
            action = "fill"
        elif _values_match(field, current, proposed):
            action = "match"
        else:
            action = "overwrite"
        changes.append(
            {
                "field": field,
                "current": current,
                "proposed": proposed,
                "action": action,
            }
        )

    # Cover art as a special entry
    has_art = existing.get("has_art", False)
    has_cover_url = bool(fetched.get("cover_url"))
    if not has_cover_url:
        art_action = "skip"
    elif not has_art:
        art_action = "fill"
    elif force:
        art_action = "overwrite"
    else:
        art_action = "match"
    changes.append(
        {
            "field": "cover_art",
            "current": "yes" if has_art else None,
            "proposed": "available" if has_cover_url else None,
            "action": art_action,
        }
    )

    return changes


def _values_match(field: str, current: object, proposed: object) -> bool:
    """Check if two metadata values are effectively the same."""
    if current == proposed:
        return True
    # Compare strings case-insensitively
    if isinstance(current, str) and isinstance(proposed, str):
        return current.strip().lower() == proposed.strip().lower()
    # Compare numbers
    if isinstance(current, (int, float)) and isinstance(proposed, (int, float)):
        return int(current) == int(proposed)
    return False


def apply_metadata(filepath: str, changes: list[dict], art_data: bytes | None = None) -> bool:
    """Write selected metadata changes to file."""
    try:
        mf = MediaFile(filepath)
        for ch in changes:
            if ch["field"] == "cover_art":
                continue  # Handled separately via art_data
            setattr(mf, ch["field"], ch["proposed"])
        if art_data:
            mf.art = art_data
        mf.save()
        return True
    except Exception as e:
        print(f"    {red('ERROR')}: {e}")
        return False


def embed_art(filepath: str, image_data: bytes) -> bool:
    """Embed cover art into audio file (legacy path)."""
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
# Cache
# ---------------------------------------------------------------------------

CACHE_FILENAME = ".music_tagger_cache.json"


def _file_fingerprint(filepath: str) -> str:
    """Quick fingerprint: mtime + size. Changes when file is modified."""
    st = os.stat(filepath)
    return f"{st.st_mtime_ns}:{st.st_size}"


def load_cache(directory: str) -> dict[str, dict]:
    """Load cache from the music directory."""
    cache_path = os.path.join(directory, CACHE_FILENAME)
    if not os.path.isfile(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data: dict[str, dict] = json.load(f)
            return data
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(directory: str, cache: dict) -> None:
    """Save cache to the music directory."""
    cache_path = os.path.join(directory, CACHE_FILENAME)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
    except OSError as e:
        print(f"  {yellow('Warning')}: could not save cache: {e}")


def get_cache_entry(cache: dict[str, dict], filepath: str) -> dict | None:
    """Get cache entry for a file, or None if not cached / stale."""
    key = os.path.basename(filepath)
    entry = cache.get(key)
    if not entry:
        return None
    try:
        if entry.get("fingerprint") != _file_fingerprint(filepath):
            return None  # File changed on disk
    except OSError:
        return None
    return entry


def is_cached(cache: dict, filepath: str) -> bool:
    """Check if a file is in the cache and hasn't been modified since."""
    return get_cache_entry(cache, filepath) is not None


def cache_metadata_matches(cache: dict, filepath: str) -> bool:
    """Check if file's current metadata matches what's stored in cache.

    Returns True if all cached metadata values still match the file.
    Returns False if anything changed (user edited tags externally, etc.).
    """
    entry = get_cache_entry(cache, filepath)
    if not entry:
        return False
    cached_meta = entry.get("file_metadata")
    if not cached_meta:
        return False
    current = read_file_metadata(filepath)
    for field in META_FIELDS:
        cached_val = cached_meta.get(field)
        current_val = current.get(field)
        if cached_val != current_val:
            # Normalize comparison for numbers stored as strings in JSON
            try:
                if cached_val is not None and current_val is not None:
                    if int(cached_val) == int(current_val):
                        continue
            except (ValueError, TypeError):
                pass
            return False
    return True


def update_cache(
    cache: dict,
    filepath: str,
    status: str,
    source: str = "",
    fetched: dict | None = None,
    file_metadata: dict | None = None,
) -> None:
    """Mark a file as processed in the cache with full metadata."""
    key = os.path.basename(filepath)
    try:
        fp = _file_fingerprint(filepath)
    except OSError:
        return

    entry: dict = {
        "fingerprint": fp,
        "status": status,
        "source": source,
        "timestamp": datetime.datetime.now().isoformat(),
    }

    # Store current file metadata for future comparison
    if file_metadata:
        entry["file_metadata"] = {f: file_metadata.get(f) for f in META_FIELDS}

    # Store what the API returned
    if fetched:
        entry["fetched_metadata"] = {f: fetched.get(f) for f in META_FIELDS}

    cache[key] = entry


# ---------------------------------------------------------------------------
# Interactive UI
# ---------------------------------------------------------------------------

_FIELD_LABELS = {
    "title": "Title",
    "artist": "Artist",
    "album": "Album",
    "albumartist": "Album Artist",
    "genre": "Genre",
    "year": "Year",
    "track": "Track",
    "tracktotal": "Track Total",
    "disc": "Disc",
    "disctotal": "Disc Total",
    "bpm": "BPM",
    "isrc": "ISRC",
    "label": "Label",
    "cover_art": "Cover Art",
}

_ACTION_SYMBOLS = {
    "fill": green("+ fill"),
    "overwrite": yellow("~ diff"),
    "match": dim("= match"),
    "skip": dim("- n/a"),
}


def _fmt_value(val: object, max_width: int = 30) -> str:
    if val is None:
        return dim("(empty)")
    s = str(val)
    if len(s) > max_width:
        s = s[: max_width - 1] + "\u2026"
    return s


def show_interactive_review(
    filepath: str,
    existing: dict,
    fetched: dict,
    changes: list[dict],
    force: bool = False,
) -> list[dict] | str:
    """Show interactive metadata review table.

    Returns:
        list[dict] — filtered list of changes to apply
        'skip' — skip this file
        'quit' — stop processing
        'auto' — apply these changes and switch to auto mode for remaining files
    """
    source = fetched.get("_source", "?")
    print(f"  Source: {bold(source)}\n")

    # Determine which changes are actionable
    actionable = []
    for ch in changes:
        if ch["action"] == "fill":
            actionable.append(ch)
        elif ch["action"] == "overwrite" and force:
            actionable.append(ch)

    # Print table header
    print(f"  {'Field':<14} {'Current':<30} {'Fetched':<30} {'Action'}")
    print(f"  {'─' * 14} {'─' * 30} {'─' * 30} {'─' * 10}")

    for ch in changes:
        label = _FIELD_LABELS.get(ch["field"], ch["field"])
        current = _fmt_value(ch["current"])
        proposed = _fmt_value(ch["proposed"])
        action = _ACTION_SYMBOLS.get(ch["action"], ch["action"])
        print(f"  {label:<14} {current:<30} {proposed:<30} {action}")

    print()

    if not actionable:
        print(f"  {dim('No changes to apply.')}")
        return []

    n_fills = sum(1 for c in actionable if c["action"] == "fill")
    n_overwrites = sum(1 for c in actionable if c["action"] == "overwrite")
    parts = []
    if n_fills:
        parts.append(f"{n_fills} fill")
    if n_overwrites:
        parts.append(f"{n_overwrites} overwrite")
    summary = ", ".join(parts)

    while True:
        try:
            answer = input(f"  Apply {summary}? [{bold('Y')}/n/s(elect)/a(uto)/q(uit)] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "quit"

        if answer in ("", "y", "yes"):
            return actionable
        elif answer in ("n", "no"):
            return "skip"
        elif answer in ("q", "quit"):
            return "quit"
        elif answer in ("s", "select"):
            return _select_fields(actionable)
        elif answer in ("a", "auto"):
            return "auto"
        else:
            print(f"  {dim('Enter Y, n, s, a, or q')}")


def _select_fields(actionable: list[dict]) -> list[dict] | str:
    """Per-field toggle selection."""
    selected = [True] * len(actionable)

    while True:
        print()
        for idx, ch in enumerate(actionable):
            label = _FIELD_LABELS.get(ch["field"], ch["field"])
            current = _fmt_value(ch["current"], 20)
            proposed = _fmt_value(ch["proposed"], 20)
            marker = green("[Y]") if selected[idx] else dim("[ ]")
            print(f"  {idx + 1}) {label:<14} {current} -> {proposed}  {marker}")

        print()
        try:
            answer = input("  Toggle numbers (e.g. 2 3), or Enter to confirm: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return "quit"

        if not answer:
            return [ch for ch, sel in zip(actionable, selected) if sel]

        for part in answer.split():
            try:
                idx = int(part) - 1
                if 0 <= idx < len(actionable):
                    selected[idx] = not selected[idx]
            except ValueError:
                pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch and embed album cover art and metadata for music files.")
    parser.add_argument(
        "directory",
        help="Path to directory containing music files",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be done without downloading or embedding",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Re-fetch/overwrite even if data already exists",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Search for music files recursively in subdirectories",
    )
    parser.add_argument(
        "-s",
        "--save-covers",
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
    parser.add_argument(
        "--tag",
        action="store_true",
        help="Enable metadata tagging (fill empty fields from API data)",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Interactive mode: review and confirm each change (implies --tag)",
    )
    parser.add_argument(
        "--strip-covers",
        action="store_true",
        help="Remove all embedded cover art from files (requires triple confirmation)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore cache and re-process all files",
    )

    args = parser.parse_args(argv)

    # --interactive implies --tag
    if args.interactive:
        args.tag = True

    if not os.path.isdir(args.directory):
        print(f"Error: '{args.directory}' is not a directory")
        return 1

    audio_files = collect_audio_files(args.directory, getattr(args, "recursive", False))
    total = len(audio_files)

    # Strip covers mode — separate path, no API calls needed
    if args.strip_covers:
        print(f"Found {total} audio files\n")
        if total == 0:
            return 0
        return _run_strip_covers(args, audio_files)

    # Filter sources based on --sources flag
    enabled = {s.strip().lower() for s in args.sources.split(",")}
    global SOURCES
    SOURCES = [(n, fn) for n, fn in SOURCES if n.lower() in enabled]
    if not SOURCES:
        print(f"Error: no valid sources in '{args.sources}'")
        print("Available: deezer, itunes, musicbrainz")
        return 1

    print(f"Sources: {', '.join(n for n, _ in SOURCES)}")
    if args.tag:
        print(f"Mode: {'interactive' if args.interactive else 'auto'} metadata tagging")

    if args.save_covers:
        os.makedirs(args.save_covers, exist_ok=True)

    print(f"Found {total} audio files\n")

    if total == 0:
        return 0

    if args.tag:
        return _run_tag_mode(args, audio_files)
    else:
        return _run_cover_only_mode(args, audio_files)


def _confirm_strip(prompt: str) -> bool:
    """Ask user for confirmation. Returns True only on explicit 'yes'."""
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer == "yes"


def _run_strip_covers(args: argparse.Namespace, audio_files: list[str]) -> int:
    """Remove embedded cover art from all files with triple confirmation."""
    # Count files that actually have art
    with_art = []
    for filepath in audio_files:
        if has_embedded_art(filepath):
            with_art.append(filepath)

    if not with_art:
        print("No files with embedded cover art found.")
        return 0

    print(f"{red(f'WARNING: This will remove cover art from {len(with_art)} file(s).')}\n")

    # Confirmation 1
    if not _confirm_strip(
        f"  [{bold('1/3')}] Remove cover art from {len(with_art)} files? Type {bold('yes')} to continue: "
    ):
        print("Aborted.")
        return 0

    # Confirmation 2
    if not _confirm_strip(
        f"  [{bold('2/3')}] This action is irreversible. Are you sure? Type {bold('yes')} to continue: "
    ):
        print("Aborted.")
        return 0

    # Confirmation 3
    if not _confirm_strip(f"  [{bold('3/3')}] Last chance. Confirm removal? Type {bold('yes')} to proceed: "):
        print("Aborted.")
        return 0

    print()

    removed = 0
    errors = 0
    for i, filepath in enumerate(with_art, 1):
        name = os.path.basename(filepath)
        try:
            mf = MediaFile(filepath)
            mf.art = None
            mf.save()
            print(f"  [{i}/{len(with_art)}] {green('Stripped')} {name}")
            removed += 1
        except Exception as e:
            print(f"  [{i}/{len(with_art)}] {red('ERROR')} {name}: {e}")
            errors += 1

    print("\n=== DONE ===")
    print(f"  Removed: {removed}")
    print(f"  Errors:  {errors}")
    print(f"  Total:   {len(with_art)}")
    return 0


def _run_cover_only_mode(args: argparse.Namespace, audio_files: list[str]) -> int:
    """Original cover-art-only workflow."""
    total = len(audio_files)
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

        result = search_all_sources(artist, title, args.resolution)
        if not result or not result.get("cover_url"):
            print("    No cover found (all sources exhausted)")
            failed += 1
            continue

        art_url = result["cover_url"]
        source_name = result.get("_source", "?")

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


def _run_tag_mode(args: argparse.Namespace, audio_files: list[str]) -> int:
    """Metadata tagging workflow (interactive or auto)."""
    total = len(audio_files)
    stats = {"tagged": 0, "skipped": 0, "not_found": 0, "errors": 0, "unchanged": 0, "cached": 0}
    source_counts: dict[str, int] = {}
    interactive = args.interactive
    report: list[dict] = []  # Collected for report generation

    # Load cache
    use_cache = not getattr(args, "no_cache", False) and not args.dry_run
    cache = load_cache(args.directory) if use_cache else {}
    if use_cache and cache:
        print(f"Cache: {len(cache)} entries loaded")

    for i, filepath in enumerate(audio_files, 1):
        # Check cache — skip files already processed and metadata unchanged
        if use_cache and not args.force and is_cached(cache, filepath):
            if cache_metadata_matches(cache, filepath):
                stats["cached"] += 1
                continue
            # File on disk matches fingerprint but metadata differs — re-process

        parsed = parse_filename(filepath)
        if not parsed:
            print(f"[{i}/{total}] SKIP (can't parse): {os.path.basename(filepath)}")
            stats["skipped"] += 1
            report.append(
                {
                    "file": os.path.basename(filepath),
                    "status": "skipped",
                    "reason": "can't parse filename",
                }
            )
            continue

        artist, title = parsed
        print(f"[{i}/{total}] {bold(artist)} - {bold(title)}")

        # Read existing metadata
        existing = read_file_metadata(filepath)

        if args.dry_run:
            empty_fields = [f for f in META_FIELDS if existing.get(f) is None]
            if not existing.get("has_art"):
                empty_fields.append("cover_art")
            if empty_fields:
                print(f"  Empty: {', '.join(empty_fields)}")
                stats["tagged"] += 1
                report.append(
                    {
                        "file": os.path.basename(filepath),
                        "artist": artist,
                        "title": title,
                        "status": "needs_fill",
                        "empty_fields": empty_fields,
                    }
                )
            else:
                print(f"  {dim('All fields populated')}")
                stats["unchanged"] += 1
                report.append(
                    {
                        "file": os.path.basename(filepath),
                        "artist": artist,
                        "title": title,
                        "status": "complete",
                    }
                )
            continue

        # Search for metadata
        result = search_all_sources(artist, title, args.resolution, metadata_mode=True)
        if not result:
            print(f"  {dim('No results found (all sources exhausted)')}")
            stats["not_found"] += 1
            if use_cache:
                update_cache(cache, filepath, "not_found", file_metadata=existing)
            report.append(
                {
                    "file": os.path.basename(filepath),
                    "artist": artist,
                    "title": title,
                    "status": "not_found",
                }
            )
            continue

        source_name = result.get("_source", "?")

        # Compute what needs changing
        changes = compute_changes(existing, result, force=args.force)

        # Filter to actionable changes
        actionable = [c for c in changes if c["action"] == "fill" or (c["action"] == "overwrite" and args.force)]

        if not actionable:
            print(f"  {dim('Nothing to update')} ({source_name})")
            stats["unchanged"] += 1
            if use_cache:
                update_cache(cache, filepath, "unchanged", source_name, fetched=result, file_metadata=existing)
            report.append(
                {
                    "file": os.path.basename(filepath),
                    "artist": artist,
                    "title": title,
                    "status": "unchanged",
                    "source": source_name,
                    "changes": changes,
                }
            )
            continue

        if interactive:
            decision = show_interactive_review(filepath, existing, result, changes, args.force)
            if decision == "quit":
                print("\nAborted by user.")
                break
            if decision == "auto":
                # Apply current file's actionable changes, then switch to auto
                print(f"  {green('Switching to auto mode for remaining files...')}")
                interactive = False
                to_apply = actionable
            elif decision == "skip" or not decision:
                print(f"  {dim('Skipped')}")
                stats["skipped"] += 1
                report.append(
                    {
                        "file": os.path.basename(filepath),
                        "artist": artist,
                        "title": title,
                        "status": "skipped",
                        "reason": "user skipped",
                        "source": source_name,
                        "changes": changes,
                    }
                )
                continue
            elif isinstance(decision, list):
                to_apply = decision
            else:
                to_apply = actionable
        else:
            to_apply = actionable
            # Show summary in auto mode
            for ch in to_apply:
                label = _FIELD_LABELS.get(ch["field"], ch["field"])
                if ch["action"] == "fill":
                    print(f"  {green('+')} {label}: {_fmt_value(ch['proposed'])}")
                elif ch["action"] == "overwrite":
                    print(f"  {yellow('~')} {label}: {_fmt_value(ch['current'])} -> {_fmt_value(ch['proposed'])}")

        # Download cover art if needed
        art_data = None
        needs_art = any(c["field"] == "cover_art" and c["action"] in ("fill", "overwrite") for c in to_apply)
        if needs_art and result.get("cover_url"):
            art_data = download_image(result["cover_url"])
            if not art_data:
                print(f"  {yellow('Cover art download failed')}")

        # Remove cover_art from the list (handled via art_data)
        meta_changes = [c for c in to_apply if c["field"] != "cover_art"]

        if not meta_changes and not art_data:
            stats["unchanged"] += 1
            report.append(
                {
                    "file": os.path.basename(filepath),
                    "artist": artist,
                    "title": title,
                    "status": "unchanged",
                    "source": source_name,
                    "changes": changes,
                }
            )
            continue

        if args.save_covers and art_data:
            safe_name = sanitize_filename(f"{artist} - {title}"[:80])
            cover_path = os.path.join(args.save_covers, f"{safe_name}.jpg")
            with open(cover_path, "wb") as f:
                f.write(art_data)

        if apply_metadata(filepath, meta_changes, art_data):
            n_changes = len(meta_changes) + (1 if art_data else 0)
            print(f"  {green('OK')} {n_changes} field(s) updated via {source_name}")
            stats["tagged"] += 1
            source_counts[source_name] = source_counts.get(source_name, 0) + 1
            if use_cache:
                # Re-read metadata after save so fingerprint and values reflect new state
                updated_meta = read_file_metadata(filepath)
                update_cache(cache, filepath, "tagged", source_name, fetched=result, file_metadata=updated_meta)
            report.append(
                {
                    "file": os.path.basename(filepath),
                    "artist": artist,
                    "title": title,
                    "status": "tagged",
                    "source": source_name,
                    "applied": [
                        {"field": c["field"], "action": c["action"], "old": c.get("current"), "new": c["proposed"]}
                        for c in meta_changes
                    ]
                    + ([{"field": "cover_art", "action": "fill"}] if art_data else []),
                }
            )
        else:
            stats["errors"] += 1
            report.append(
                {
                    "file": os.path.basename(filepath),
                    "artist": artist,
                    "title": title,
                    "status": "error",
                    "source": source_name,
                }
            )

    # Save cache
    if use_cache and cache:
        save_cache(args.directory, cache)

    # Print summary
    print(f"\n{'=== DRY RUN ===' if args.dry_run else '=== DONE ==='}")
    if stats["cached"]:
        print(f"  Cached:     {stats['cached']}")
    print(f"  Tagged:     {stats['tagged']}")
    if source_counts:
        for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
            print(f"    {src}: {cnt}")
    print(f"  Unchanged:  {stats['unchanged']}")
    print(f"  Not found:  {stats['not_found']}")
    print(f"  Errors:     {stats['errors']}")
    print(f"  Skipped:    {stats['skipped']}")
    print(f"  Total:      {total}")

    # Generate report
    if report:
        report_path = _write_report(args.directory, report, stats, source_counts, args.dry_run)
        print(f"\n  Report: {report_path}")

    return 0


def _write_report(
    directory: str,
    report: list[dict],
    stats: dict,
    source_counts: dict[str, int],
    dry_run: bool,
) -> str:
    """Write a detailed report file to the music directory root."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    prefix = "dryrun_" if dry_run else ""
    report_name = f"{prefix}tag_report_{timestamp}.txt"
    report_path = os.path.join(directory, report_name)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"Music Tagger Report — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        if dry_run:
            f.write("MODE: DRY RUN (no changes applied)\n")
        f.write(f"Directory: {directory}\n")
        f.write("=" * 70 + "\n\n")

        # Summary
        f.write("SUMMARY\n")
        f.write("-" * 40 + "\n")
        for key, val in stats.items():
            f.write(f"  {key:<12} {val}\n")
        if source_counts:
            f.write("\n  Sources:\n")
            for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
                f.write(f"    {src}: {cnt}\n")
        f.write("\n" + "=" * 70 + "\n\n")

        # Per-file details
        f.write("DETAILS\n")
        f.write("-" * 40 + "\n\n")

        for entry in report:
            filename = entry["file"]
            status = entry["status"].upper()
            f.write(f"  [{status}] {filename}\n")

            if entry.get("source"):
                f.write(f"    Source: {entry['source']}\n")

            if entry.get("reason"):
                f.write(f"    Reason: {entry['reason']}\n")

            if entry.get("empty_fields"):
                f.write(f"    Empty fields: {', '.join(entry['empty_fields'])}\n")

            if entry.get("applied"):
                for ch in entry["applied"]:
                    field = _FIELD_LABELS.get(ch["field"], ch["field"])
                    if ch.get("old") is not None:
                        f.write(f"    {ch['action']:>9} {field}: {ch['old']} -> {ch.get('new', '')}\n")
                    else:
                        f.write(f"    {ch['action']:>9} {field}: {ch.get('new', '')}\n")

            # Show diffs for unchanged/skipped files that have change data
            if entry.get("changes") and entry["status"] in ("unchanged", "skipped"):
                diffs = [c for c in entry["changes"] if c["action"] == "overwrite"]
                if diffs:
                    f.write("    Diffs detected (not applied):\n")
                    for c in diffs:
                        label = _FIELD_LABELS.get(c["field"], c["field"])
                        f.write(f"      {label}: {c['current']} vs {c['proposed']}\n")

            f.write("\n")

    return report_path


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    raise SystemExit(main())

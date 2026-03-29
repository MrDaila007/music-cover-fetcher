# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Single-file Python CLI tool that fetches album cover art from multiple APIs (Deezer, iTunes, MusicBrainz/Cover Art Archive) and embeds it into audio file metadata. Parses `Artist - Title` from filenames.

## Running

```bash
# Basic usage
python music_cover_fetcher.py /path/to/music

# Dry run, recursive, force re-fetch
python music_cover_fetcher.py /path/to/music --dry-run --recursive --force

# Limit sources
python music_cover_fetcher.py /path/to/music --sources deezer,itunes
```

## Dependencies

```bash
pip install requests mediafile
```

Requires Python >=3.10 (uses `X | Y` union types).

## Architecture

Everything lives in `music_cover_fetcher.py`. Key structure:

- **Filename parsing**: `parse_filename()` extracts artist/title; `build_search_queries()` generates query variations (normalized text, first artist only, etc.)
- **Source functions**: `search_deezer()`, `search_itunes()`, `search_musicbrainz()` — each returns a cover art URL or None. Registered in the `SOURCES` list (priority order). `search_all_sources()` iterates sources × query variations with rate limiting.
- **File operations**: `collect_audio_files()`, `has_embedded_art()`, `embed_art()` — uses the `mediafile` library for tag reading/writing across all supported formats.
- **`main()`**: Orchestrates the pipeline with argparse CLI. Mutates global `SOURCES` based on `--sources` flag.

## Notes

- MusicBrainz requires a `User-Agent` header; currently hardcoded in `search_musicbrainz()`.
- Rate limiting is a flat `0.3s` sleep between API calls (`RATE_LIMIT_SECONDS`).
- Images smaller than `MIN_IMAGE_SIZE` (1000 bytes) are rejected as likely error responses.
- No test suite exists yet.

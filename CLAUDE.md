# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Single-file Python CLI tool that fetches album cover art and metadata from multiple APIs (Deezer, iTunes, MusicBrainz/Cover Art Archive) and embeds them into audio file tags. Parses `Artist - Title` from filenames.

## Running

```bash
# Cover art only (default)
python music_cover_fetcher.py /path/to/music

# Auto-fill empty metadata fields
python music_cover_fetcher.py /path/to/music --tag

# Interactive mode: review changes per file (implies --tag)
python music_cover_fetcher.py /path/to/music -i

# Force overwrite existing fields
python music_cover_fetcher.py /path/to/music -i --force

# Dry run, recursive, limit sources
python music_cover_fetcher.py /path/to/music --tag --dry-run --recursive --sources deezer,itunes
```

## Dependencies

```bash
pip install requests mediafile
```

Requires Python >=3.10 (uses `X | Y` union types).

## Architecture

Everything lives in `music_cover_fetcher.py`. Key structure:

- **Filename parsing**: `parse_filename()` extracts artist/title; `build_search_queries()` generates query variations (normalized text, first artist only, etc.)
- **Source functions**: `search_deezer()`, `search_itunes()`, `search_musicbrainz()` — each returns a metadata `dict` (title, artist, album, genre, year, track, disc, bpm, isrc, cover_url, etc.) or None. Registered in `SOURCES` list (priority order).
- **`search_all_sources()`**: iterates sources x query variations with rate limiting. In `metadata_mode=True`, prefers results with more filled fields rather than stopping at first hit.
- **`_match_score()`**: shared artist/title fuzzy matching used by all source functions to rank API results.
- **Metadata operations**: `read_file_metadata()` reads current tags, `compute_changes()` diffs existing vs fetched (fill/overwrite/match/skip), `apply_metadata()` writes changes via MediaFile.
- **Interactive UI**: `show_interactive_review()` displays a colored diff table with Y/n/s(elect)/a(uto)/q(uit) prompt. `_select_fields()` handles per-field toggle. Auto mode (`a`) switches off interactive for remaining files.
- **Report**: `_write_report()` generates a text report in the music directory with per-file details and diffs.
- **Two main paths**: `_run_cover_only_mode()` (default, legacy) and `_run_tag_mode()` (with `--tag`/`-i`). `main()` dispatches between them.

## Notes

- MusicBrainz requires a `User-Agent` header; hardcoded in `search_musicbrainz()`.
- Rate limiting is a flat `0.3s` sleep between API calls (`RATE_LIMIT_SECONDS`).
- Images smaller than `MIN_IMAGE_SIZE` (1000 bytes) are rejected as likely error responses.
- Numeric metadata values of `0` are treated as empty (common default in tag libraries).
- ANSI colors are auto-detected via `isatty()` and disabled when piped.
- No test suite exists yet.

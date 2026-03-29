# music-cover-fetcher

Auto-tag your music library — fetches cover art, album, genre, year, track numbers and more from Deezer, iTunes & MusicBrainz.

Parses `Artist - Title` from filenames, searches multiple APIs, and embeds artwork and metadata directly into file tags. Supports interactive review, smart caching, and detailed reports.

## Sources

Searches are tried in order until a match is found:

1. **Deezer** — free API, no key needed, good international coverage
2. **iTunes** — Apple's search API, strong for mainstream music
3. **MusicBrainz / Cover Art Archive** — open database, good for less common releases

Each source is tried with multiple query variations (normalized text, first artist only, etc.) to maximize hit rate.

## Metadata fields

When using `--tag` or `-i`, the following fields are filled from API data:

| Field | Deezer | iTunes | MusicBrainz |
|-------|--------|--------|-------------|
| Title | + | + | + |
| Artist | + | + | + |
| Album | + | + | + |
| Genre | - | + | - |
| Year | - | + | + |
| Track / Total | + | + | - |
| Disc / Total | + | + | - |
| BPM | + | - | - |
| ISRC | + | - | + |
| Cover Art | + | + | + |

## Supported formats

MP3, M4A, FLAC, OGG, Opus, WMA, WAV

## Quick start (Windows)

```bat
setup.bat
run.bat C:\Music -i
```

## Installation

### With venv (recommended)

```bash
# Windows
setup.bat

# Or manually
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

### Without venv

```bash
pip install requests mediafile
```

### With Make

```bash
make setup
```

## Usage

### Via run.bat (Windows)

```bat
run.bat C:\Music                     # cover art only
run.bat C:\Music --tag               # auto-fill metadata
run.bat C:\Music -i                  # interactive mode
run.bat C:\Music --strip-covers      # remove all covers
```

### Via Make

```bash
make tag MUSIC=C:\Music              # auto-fill metadata
make interactive MUSIC=C:\Music      # interactive mode
make dry-run MUSIC=C:\Music          # preview changes
make strip-covers MUSIC=C:\Music     # remove all covers
```

### Direct

```bash
python music_cover_fetcher.py /path/to/music              # cover art only
python music_cover_fetcher.py /path/to/music --tag         # auto-fill metadata
python music_cover_fetcher.py /path/to/music -i            # interactive mode
python music_cover_fetcher.py /path/to/music -i --force    # overwrite existing fields
python music_cover_fetcher.py /path/to/music --tag --dry-run       # preview
python music_cover_fetcher.py /path/to/music -i --recursive        # search subdirs
python music_cover_fetcher.py /path/to/music --save-covers ./covers
python music_cover_fetcher.py /path/to/music --resolution 1200
python music_cover_fetcher.py /path/to/music --sources deezer,itunes
python music_cover_fetcher.py /path/to/music --tag --no-cache      # ignore cache
python music_cover_fetcher.py /path/to/music --strip-covers        # remove covers
```

### Modes

- **Default** (no flags) — cover art only, same as before
- **`--tag`** — automatically fill empty metadata fields from APIs
- **`-i` / `--interactive`** — review a table of current vs. fetched values per file; choose to apply all, select individual fields, switch to auto, or quit
- **`--force`** — overwrite existing metadata (not just fill empty fields)
- **`--strip-covers`** — remove all embedded cover art (requires triple confirmation)
- **`--no-cache`** — ignore cache and re-process all files

### Interactive controls

| Key | Action |
|-----|--------|
| `Y` (default) | Apply all proposed changes for this file |
| `n` | Skip this file |
| `s` | Select individual fields to apply |
| `a` | Switch to auto mode — apply current file and all remaining automatically |
| `q` | Quit processing |

### Reports

When running with `--tag` or `-i`, a report file is generated in the music directory after processing:

```
tag_report_2025-03-29_14-30-00.txt
```

The report contains a summary and per-file details: what was changed, what was skipped, and any metadata discrepancies detected between existing tags and API data.

### Cache

Processed files are cached in `.music_tagger_cache.json` in the music directory. On subsequent runs, files that haven't changed since last processing are skipped automatically. The cache is invalidated when a file's modification time or size changes.

- `--force` ignores the cache and re-checks all files
- `--no-cache` disables caching entirely
- Cache is not used during `--dry-run`

## How it works

1. Scans the directory for audio files
2. Checks cache — skips already processed files that haven't changed
3. Parses `Artist - Title` from each filename
4. Builds multiple search query variations (normalized text, first artist, etc.)
5. Tries each source in order: Deezer, iTunes, MusicBrainz
6. Compares fetched metadata against existing file tags
7. Fills empty fields (or overwrites with `--force`), embeds cover art
8. Updates cache and generates a report
9. Rate-limits requests to respect APIs

## Filename format

Files must follow the pattern:

```
Artist - Title.mp3
Artist feat. Other - Title (Extra Info).flac
```

Files that don't match this pattern are skipped.

## License

Apache License 2.0

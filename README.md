# music-cover-fetcher

Fetch and embed album cover art and metadata for music files using multiple sources.

Parses artist and title from filenames (`Artist - Title.mp3`), searches multiple APIs for matching data, and embeds artwork and metadata directly into the file's tags.

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

## Installation

```bash
pip install requests mediafile
```

## Usage

```bash
# Fetch covers for all music files in a directory (original behavior)
python music_cover_fetcher.py /path/to/music

# Fill empty metadata fields automatically
python music_cover_fetcher.py /path/to/music --tag

# Interactive mode: review each change before applying
python music_cover_fetcher.py /path/to/music -i

# Interactive mode with overwrite of existing fields
python music_cover_fetcher.py /path/to/music -i --force

# Preview what would be done
python music_cover_fetcher.py /path/to/music --tag --dry-run

# Search subdirectories recursively
python music_cover_fetcher.py /path/to/music -i --recursive

# Save cover images to a separate folder
python music_cover_fetcher.py /path/to/music --save-covers ./covers

# Use higher resolution artwork (default: 600px)
python music_cover_fetcher.py /path/to/music --resolution 1200

# Use only specific sources
python music_cover_fetcher.py /path/to/music --sources deezer,itunes
```

### Modes

- **Default** (no flags) — cover art only, same as before
- **`--tag`** — automatically fill empty metadata fields from APIs
- **`-i` / `--interactive`** — review a table of current vs. fetched values per file; choose to apply all, select individual fields, switch to auto, or quit
- **`--force`** — overwrite existing metadata (not just fill empty fields)

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

## How it works

1. Scans the directory for audio files
2. Parses `Artist - Title` from each filename
3. Builds multiple search query variations (normalized text, first artist, etc.)
4. Tries each source in order: Deezer, iTunes, MusicBrainz
5. Compares fetched metadata against existing file tags
6. Fills empty fields (or overwrites with `--force`), embeds cover art
7. Rate-limits requests to respect APIs

## Filename format

Files must follow the pattern:

```
Artist - Title.mp3
Artist feat. Other - Title (Extra Info).flac
```

Files that don't match this pattern are skipped.

## License

Apache License 2.0

# music-cover-fetcher

Fetch and embed album cover art for music files using multiple sources.

Parses artist and title from filenames (`Artist - Title.mp3`), searches multiple APIs for matching cover art, and embeds it directly into the file's tags.

## Sources

Searches are tried in order until a match is found:

1. **Deezer** — free API, no key needed, good international coverage
2. **iTunes** — Apple's search API, strong for mainstream music
3. **MusicBrainz / Cover Art Archive** — open database, good for less common releases

Each source is tried with multiple query variations (normalized text, first artist only, etc.) to maximize hit rate.

## Supported formats

MP3, M4A, FLAC, OGG, Opus, WMA, WAV

## Installation

```bash
pip install requests mediafile
```

## Usage

```bash
# Fetch covers for all music files in a directory
python music_cover_fetcher.py /path/to/music

# Preview what would be done
python music_cover_fetcher.py /path/to/music --dry-run

# Re-fetch covers even for files that already have art
python music_cover_fetcher.py /path/to/music --force

# Search subdirectories recursively
python music_cover_fetcher.py /path/to/music --recursive

# Save cover images to a separate folder
python music_cover_fetcher.py /path/to/music --save-covers ./covers

# Use higher resolution artwork (default: 600px)
python music_cover_fetcher.py /path/to/music --resolution 1200

# Use only specific sources
python music_cover_fetcher.py /path/to/music --sources deezer,itunes
```

## How it works

1. Scans the directory for audio files
2. Parses `Artist - Title` from each filename
3. Builds multiple search query variations (normalized text, first artist, etc.)
4. Tries each source in order: Deezer, iTunes, MusicBrainz
5. Downloads the first match and embeds it into the file's metadata
6. Rate-limits requests to respect APIs

## Filename format

Files must follow the pattern:

```
Artist - Title.mp3
Artist feat. Other - Title (Extra Info).flac
```

Files that don't match this pattern are skipped.

## License

Apache License 2.0

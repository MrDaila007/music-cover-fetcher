# music-cover-fetcher

Fetch and embed album cover art for music files using the iTunes Search API.

Parses artist and title from filenames (`Artist - Title.mp3`), searches iTunes for matching cover art, and embeds it directly into the file's tags.

## Supported formats

MP3, M4A, FLAC, OGG, Opus, WMA, WAV

## Installation

```bash
pip install .
```

Or install directly with dependencies:

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
```

## How it works

1. Scans the directory for audio files
2. Parses `Artist - Title` from each filename
3. Searches the [iTunes Search API](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/) for matching tracks
4. Downloads the cover art and embeds it into the file's metadata tags
5. Rate-limits requests to respect the API

## Filename format

Files must follow the pattern:

```
Artist - Title.mp3
Artist feat. Other - Title (Extra Info).flac
```

Files that don't match this pattern are skipped.

## License

MIT

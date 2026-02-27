---
name: video-converter
description: Convert videos in a directory to a specified aspect ratio with intelligent cropping using ffmpeg. Works with relative dimensions instead of absolute pixels for maximum flexibility. Use this skill when the human asks to crop a video or directory of videos to a specific aspect ratio.
---

# Video Converter

Intelligent video conversion tool using ffmpeg with aspect-ratio-based cropping and scaling.

## Quick Start

```bash
# Convert to 9:16 vertical (TikTok/Reels)
./scripts/video_converter.py /path/to/videos --aspect-ratio 9:16

# Remove left 20%, create 9:16 aligned left, scale to 1920px
./scripts/video_converter.py /path/to/videos --aspect-ratio 9:16 --max-dimension 1920 --crop-x 20% --crop-align-x left
```

## Core Algorithm

When aspect ratio and edge cropping are specified:

1. **Edge Removal**: `--crop-x` and `--crop-y` remove portions from edges
   - `--crop-x 20%` removes the leftmost 20% of the video  
   - `--crop-y 10%` removes the topmost 10% of the video

2. **Aspect Ratio Maximization**: Within remaining area, create the largest possible crop matching target aspect ratio
   - If `--aspect-ratio 9:16`, crop will have width:height = 9:16
   - Crop is maximized to fill as much of remaining area as possible

3. **Alignment Positioning**: Position final crop using alignment parameters
   - `--crop-align-x left|center|right` (horizontal)
   - `--crop-align-y top|center|bottom` (vertical)

## Installation

Automatic (macOS with Homebrew):
```bash
./scripts/video_converter.py /path --auto-install-deps
```

Manual:
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian  
sudo apt-get install ffmpeg
```

## Usage Examples

### Aspect Ratio Conversion

```bash
# 16:9 widescreen
./scripts/video_converter.py ~/Videos/input --aspect-ratio 16:9

# 9:16 vertical (TikTok/Reels/Stories)
./scripts/video_converter.py ~/Videos/input --aspect-ratio 9:16

# 1:1 square (Instagram posts)
./scripts/video_converter.py ~/Videos/input --aspect-ratio 1:1

# 4:3 (Instagram landscape)
./scripts/video_converter.py ~/Videos/input --aspect-ratio 4:3
```

### Edge Removal + Aspect Ratio

```bash
# Remove left 20%, create 9:16 aligned left
./scripts/video_converter.py ~/Videos/input --aspect-ratio 9:16 --crop-x 20% --crop-align-x left

# Remove left 20%, center the crop
./scripts/video_converter.py ~/Videos/input --aspect-ratio 9:16 --crop-x 20% --crop-align-x center

# Remove top 10%, align to bottom
./scripts/video_converter.py ~/Videos/input --aspect-ratio 16:9 --crop-y 10% --crop-align-y bottom

# Remove left 15% AND top 10%, center both ways
./scripts/video_converter.py ~/Videos/input --aspect-ratio 4:3 --crop-x 15% --crop-y 10% --crop-align-x center --crop-align-y center
```

### Resolution Control

```bash
# Scale to 1080p (larger dimension = 1080)
./scripts/video_converter.py ~/Videos/input --aspect-ratio 16:9 --max-dimension 1080

# Scale to 1920p (for 9:16 vertical, height becomes 1920)
./scripts/video_converter.py ~/Videos/input --aspect-ratio 9:16 --max-dimension 1920

# 4K output
./scripts/video_converter.py ~/Videos/input --aspect-ratio 16:9 --max-dimension 3840
```

Note: Supports both upscaling and downscaling.

### Quality Settings

```bash
# High quality (CRF 18, slower, larger files)
./scripts/video_converter.py ~/Videos/input --aspect-ratio 16:9 --crf 18 --preset slow

# Balanced (default: CRF 23, medium preset)
./scripts/video_converter.py ~/Videos/input --aspect-ratio 16:9

# Fast encoding (lower quality, smaller files)
./scripts/video_converter.py ~/Videos/input --aspect-ratio 16:9 --crf 28 --preset fast

# H.265 codec for better compression
./scripts/video_converter.py ~/Videos/input --aspect-ratio 16:9 --codec libx265
```

CRF Scale: 0 (lossless) to 51 (worst)
- 18-20: Very high quality
- 23: Default (good quality)
- 28-30: Lower quality, smaller files

### Batch Processing

```bash
# Process subdirectories recursively
./scripts/video_converter.py ~/Videos/input --aspect-ratio 16:9 --recursive

# Dry run (preview without converting)
./scripts/video_converter.py ~/Videos/input --aspect-ratio 16:9 --dry-run

# Debug mode (verbose logging)
./scripts/video_converter.py ~/Videos/input --aspect-ratio 16:9 --debug

# Overwrite existing files
./scripts/video_converter.py ~/Videos/input --aspect-ratio 16:9 --overwrite
```

## Social Media Formats

### TikTok / Instagram Reels / YouTube Shorts (9:16)
```bash
./scripts/video_converter.py ~/Videos/raw --aspect-ratio 9:16 --max-dimension 1920 --recursive
```

### Instagram Feed Post (1:1 square)
```bash
./scripts/video_converter.py ~/Videos/raw --aspect-ratio 1:1 --max-dimension 1080
```

### YouTube / Vimeo (16:9 widescreen)
```bash
./scripts/video_converter.py ~/Videos/raw --aspect-ratio 16:9 --max-dimension 1080 --crf 20 --preset slow
```

## Troubleshooting

### ffmpeg not found
Install ffmpeg or use `--auto-install-deps`:
```bash
./scripts/video_converter.py /path --auto-install-deps --aspect-ratio 9:16
```

### No video files found
Check directory contains supported formats (`.mp4`, `.mov`, `.avi`, `.mkv`, `.flv`, `.wmv`, `.m4v`, `.webm`, `.mpg`, `.mpeg`):
```bash
ls /path/to/videos
```

### Invalid aspect ratio format
Use format like `16:9`, `9:16`, `4:3`, `1:1`:
```bash
# Correct
--aspect-ratio 9:16

# Incorrect
--aspect-ratio 0.5625  # Use 9:16
--aspect-ratio 9x16    # Use : not x
```

### Percentage cannot exceed 100%
Use values between 0% and 100%:
```bash
# Correct
--crop-x 20%

# Incorrect
--crop-x 120%
```

### Conversion is very slow
- Use faster preset: `--preset fast`
- Reduce resolution: `--max-dimension 720`

### Output files too large
- Increase CRF: `--crf 28`
- Use H.265: `--codec libx265`
- Lower audio bitrate: `--audio-bitrate 128k`

### Poor quality output
- Decrease CRF: `--crf 18`
- Use slower preset: `--preset slow`
- Increase audio bitrate: `--audio-bitrate 256k`

## API Reference

### Parameters

**Required:**
- `input_dir`: Directory containing videos

**Aspect Ratio & Cropping:**
- `--aspect-ratio RATIO`: Target aspect ratio (e.g., `9:16`, `16:9`, `4:3`, `1:1`)
- `--crop-x OFFSET`: How far from LEFT edge to start crop (e.g., `20%`)
- `--crop-y OFFSET`: How far from TOP edge to start crop (e.g., `10%`)
- `--crop-align-x {left,center,right}`: Horizontal alignment (default: `left`)
- `--crop-align-y {top,center,bottom}`: Vertical alignment (default: `top`)
- `--crop-width WIDTH`: Manual crop width (overrides aspect ratio)
- `--crop-height HEIGHT`: Manual crop height (overrides aspect ratio)

**Output Format:**
- `--output-dir DIR`: Output directory (default: `<input_dir>_converted`)
- `--format FORMAT`: Output format (default: `mp4`)
- `--codec CODEC`: Video codec (default: `libx264`)
- `--max-dimension PIXELS`: Max width/height preserving aspect ratio
- `--crf VALUE`: Quality 0-51, lower=better (default: `23`)
- `--preset PRESET`: Speed vs compression (default: `medium`)
- `--audio-codec CODEC`: Audio codec (default: `aac`)
- `--audio-bitrate BITRATE`: Audio bitrate (default: `192k`)

**Behavior:**
- `--recursive`: Process subdirectories
- `--overwrite`: Overwrite existing files
- `--dry-run`: Show commands without executing
- `--debug`: Enable debug logging
- `--auto-install-deps`: Auto-install ffmpeg (macOS only, requires Homebrew)

### Exit Codes
- `0`: Success
- `1`: Error (missing deps, no files, conversion failures)
- `2`: Invalid arguments

### Programmatic Usage

```python
from pathlib import Path
from video_converter import VideoConverter

converter = VideoConverter(
    aspect_ratio='9:16',
    max_dimension=1920,
    crf=23,
    crop_align_x='left',
    crop_align_y='top'
)

successful, failed = converter.process_directory(
    input_dir=Path('/path/to/videos'),
    output_dir=Path('/path/to/output'),
    crop_x='20%',
    recursive=True
)

print(f"Converted {successful} videos, {failed} failed")
```

## For Future Agents

### When to Use
- Converting videos to specific aspect ratios for social media
- Batch processing video directories
- Removing unwanted edges before cropping
- Creating consistent output formats
- Resizing videos while maintaining aspect ratio

### Key Parameters
1. `--aspect-ratio`: ALWAYS specify for smart auto-cropping (e.g., `9:16` for vertical)
2. `--crop-x` / `--crop-y`: Use to REMOVE edges BEFORE aspect ratio crop
3. `--crop-align-x` / `--crop-align-y`: Controls WHERE final crop sits
4. `--max-dimension`: Scales output (supports upscaling AND downscaling)
5. `--recursive`: Don't forget for nested directories

### Common Patterns
```bash
# Simple aspect ratio conversion
--aspect-ratio 9:16

# Remove edge + aspect ratio + alignment
--aspect-ratio 9:16 --crop-x 20% --crop-align-x left

# Full control with scaling
--aspect-ratio 9:16 --crop-x 20% --crop-align-x center --max-dimension 1920

# Always dry run first
--aspect-ratio 9:16 --dry-run
```

### Errorhandling
- Empty directories → Warns and exits gracefully
- Corrupted videos → Logs error, continues with next file
- Missing output directory → Creates automatically
- Existing output files → Skips by default (use `--overwrite`)
- Percentage > 100% → Validation error with clear message
- Invalid dimensions → Detailed error with ffprobe suggestion

### Testing
```bash
# Always test with dry-run first
./scripts/video_converter.py /test/path --aspect-ratio 9:16 --dry-run

# Test single directory before recursive
./scripts/video_converter.py /test/path --aspect-ratio 9:16
# Then add --recursive if needed

# Debug for troubleshooting
./scripts/video_converter.py /test/path --aspect-ratio 9:16 --debug
```

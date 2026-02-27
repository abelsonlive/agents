
---
name: video-converter
description: Convert videos in a directory to a specified aspect ratio with intelligent cropping using ffmpeg. Works with relative dimensions instead of absolute pixels for maximum flexibility. Use this skill when the human asks to crop a video or directory of videos to a specific aspect ratio.
---

## Video Converter

Convert videos in a directory to a specified aspect ratio with intelligent cropping using ffmpeg. Works with relative dimensions instead of absolute pixels for maximum flexibility.

**Key Features:**
- Aspect ratio-based conversion (e.g., 16:9, 4:3, 9:16, 1:1)
- Edge-based cropping with alignment control
- Automatic scaling with quality control
- Recursive directory processing
- Percentage-based positioning

**How Cropping Works:**
1. Remove specified amount from edges (e.g., `--crop-x 20%` discards left 20%)
2. Create maximum-sized crop matching target aspect ratio from remaining area
3. Position final crop using alignment parameters (`--crop-align-x`, `--crop-align-y`)

### Installation

The skill will automatically check for ffmpeg and offer to install it on macOS using Homebrew if it's missing.

For manual installation:
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg
```

To auto-install dependencies without prompting (useful for scripts):
```bash
./scripts/video_converter.py /path/to/videos --auto-install-deps
```

### Basic Usage

```bash
# Convert all videos to 16:9 aspect ratio (auto-crops and scales)
./scripts/video_converter.py /path/to/videos --aspect-ratio 16:9

# Convert to 4:3 aspect ratio with max dimension of 1080p
./scripts/video_converter.py /path/to/videos --aspect-ratio 4:3 --max-dimension 1080

# Specify output directory
./scripts/video_converter.py /path/to/videos --aspect-ratio 16:9 --output-dir /path/to/output
```

### Aspect Ratio Conversion

The skill intelligently crops and scales videos to match the target aspect ratio:

```bash
# Convert to Instagram landscape (4:3)
./scripts/video_converter.py ~/Videos/input --aspect-ratio 4:3

# Convert to widescreen (16:9)
./scripts/video_converter.py ~/Videos/input --aspect-ratio 16:9

# Convert to square (1:1) - perfect for Instagram posts
./scripts/video_converter.py ~/Videos/input --aspect-ratio 1:1

# Convert to vertical video (9:16) - TikTok/Reels/Stories
./scripts/video_converter.py ~/Videos/input --aspect-ratio 9:16

# Convert to ultra-wide (21:9)
./scripts/video_converter.py ~/Videos/input --aspect-ratio 21:9
```

### Custom Cropping with Aspect Ratio

**Cropping Algorithm:**
1. `--crop-x` and `--crop-y` define how much to remove from edges (e.g., `--crop-x 20%` removes the left 20%)
2. Within the remaining area, the aspect ratio crop is positioned using `--crop-align-x` and `--crop-align-y`
3. The final crop is maximized to fit the aspect ratio

```bash
# Remove left 20%, create 9:16 crop aligned to left of remaining area
./scripts/video_converter.py ~/Videos/input \
  --aspect-ratio 9:16 \
  --crop-x 20% \
  --crop-align-x left

# Remove left 20%, center the 9:16 crop in remaining area
./scripts/video_converter.py ~/Videos/input \
  --aspect-ratio 9:16 \
  --crop-x 20% \
  --crop-align-x center

# Remove top 10%, align 16:9 crop to bottom of remaining area
./scripts/video_converter.py ~/Videos/input \
  --aspect-ratio 16:9 \
  --crop-y 10% \
  --crop-align-y bottom

# Remove left 15% and top 10%, center both directions
./scripts/video_converter.py ~/Videos/input \
  --aspect-ratio 4:3 \
  --crop-x 15% \
  --crop-y 10% \
  --crop-align-x center \
  --crop-align-y center
```

**Alignment Options:**
- `--crop-align-x`: `left` (default), `center`, or `right`
- `--crop-align-y`: `top` (default), `center`, or `bottom`

### Resolution Control

Control output resolution while maintaining aspect ratio:

```bash
# Limit output to 1080p max (maintains aspect ratio)
./scripts/video_converter.py ~/Videos/input \
  --aspect-ratio 16:9 \
  --max-dimension 1080

# Limit to 720p
./scripts/video_converter.py ~/Videos/input \
  --aspect-ratio 16:9 \
  --max-dimension 720

# 4K output (max 3840)
./scripts/video_converter.py ~/Videos/input \
  --aspect-ratio 16:9 \
  --max-dimension 3840
```

### Quality & Format Settings

```bash
# High quality (lower CRF = better quality, larger file)
./scripts/video_converter.py ~/Videos/input \
  --aspect-ratio 16:9 \
  --crf 18

# Fast encoding
./scripts/video_converter.py ~/Videos/input \
  --aspect-ratio 4:3 \
  --preset fast

# Use H.265 codec for better compression
./scripts/video_converter.py ~/Videos/input \
  --aspect-ratio 16:9 \
  --codec libx265

# Custom audio settings
./scripts/video_converter.py ~/Videos/input \
  --aspect-ratio 16:9 \
  --audio-codec aac \
  --audio-bitrate 256k
```

### Advanced Options

```bash
# Process subdirectories recursively
./scripts/video_converter.py ~/Videos/input --recursive

# Dry run (see what would happen without converting)
./scripts/video_converter.py ~/Videos/input --aspect-ratio 16:9 --dry-run

# Overwrite existing files
./scripts/video_converter.py ~/Videos/input --aspect-ratio 16:9 --overwrite
```

### Understanding Crop Parameters

When using `--aspect-ratio`, the skill automatically determines the crop dimensions needed. You can override the crop position:

- `--crop-x`: Starting X position (left edge of crop area)
  - Use `20%` for 20% from left
  - Use `center` to center horizontally (default when cropping width)
  - Percentages are relative to each video's dimensions

- `--crop-y`: Starting Y position (top edge of crop area)
  - Use `10%` for 10% from top
  - Use `center` to center vertically (default when cropping height)
  - Percentages are relative to each video's dimensions

- `--crop-width` / `--crop-height`: Manual crop dimensions (rarely needed)
  - Use `60%` for 60% of original dimension
  - The skill auto-calculates these from aspect ratio

### Common Use Cases

**Instagram Landscape (4:3)**
```bash
./scripts/video_converter.py ~/Desktop/videos \
  --aspect-ratio 4:3 \
  --max-dimension 1080
```

**Instagram Square Post (1:1)**
```bash
./scripts/video_converter.py ~/Desktop/videos \
  --aspect-ratio 1:1 \
  --max-dimension 1080
```

**YouTube Shorts / TikTok / Reels (9:16)**
```bash
./scripts/video_converter.py ~/Desktop/videos \
  --aspect-ratio 9:16 \
  --max-dimension 1920
```

**Instagram Story (9:16)**
```bash
./scripts/video_converter.py ~/Desktop/videos \
  --aspect-ratio 9:16 \
  --max-dimension 1920
```

**Standard HD YouTube (16:9)**
```bash
./scripts/video_converter.py ~/Desktop/videos \
  --aspect-ratio 16:9 \
  --max-dimension 1080
```

**Cinematic Widescreen (21:9)**
```bash
./scripts/video_converter.py ~/Desktop/videos \
  --aspect-ratio 21:9 \
  --max-dimension 1080
```

**Custom crop position for 4:3, offset from left**
```bash
./scripts/video_converter.py ~/Desktop/videos \
  --aspect-ratio 4:3 \
  --crop-x 17% \
  --max-dimension 1080
```

### How It Works

1. **Aspect Ratio Detection**: The skill analyzes each video's current aspect ratio
2. **Intelligent Cropping**: If the video doesn't match the target aspect ratio, it automatically crops to fit (centered by default)
3. **Smart Scaling**: After cropping, scales to the desired maximum dimension while preserving the aspect ratio
4. **Relative Dimensions**: All operations use percentages and aspect ratios, not fixed pixel values, so it works with any input resolution

This approach ensures consistent output across videos of different sizes while maintaining quality and flexibility.

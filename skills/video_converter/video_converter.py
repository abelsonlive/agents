#!/usr/bin/env python3
"""Video Conversion Skill

Converts videos in a directory to a specified aspect ratio with intelligent cropping.
Uses ffmpeg for processing. Works with relative dimensions instead of absolute pixels.

**Key Algorithm:**
1. crop-x/crop-y: Remove edges from the video (e.g., --crop-x 20% discards left 20%)
2. Within remaining area, maximize crop size to match target aspect ratio
   3. Position final crop using --crop-align-x and --crop-align-y (left/center/right, top/center/bottom)
4. Scale to match --max-dimension if specified

**Common Use Cases:**
    # Remove left 20%, create 9:16 vertical crop aligned left, scale to 1920px
    python video_converter.py /path/to/videos --aspect-ratio 9:16 --max-dimension 1920 --crop-x 20%
    
    # Create centered 16:9 crop without removing edges
    python video_converter.py /path/to/videos --aspect-ratio 16:9
    
    # Remove left 15% and top 10%, center the 4:3 crop in remaining area
    python video_converter.py /path/to/videos --aspect-ratio 4:3 --crop-x 15% --crop-y 10% --crop-align-x center --crop-align-y center

**Error Handling:**
- Validates input directory exists
- Checks for ffmpeg installation and offers auto-install on macOS
- Validates aspect ratio format
- Handles corrupt/unsupported video files gracefully
- Continues processing remaining files on individual failures
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.m4v', '.webm', '.mpg', '.mpeg'}


class VideoConversionError(Exception):
    """Custom exception for video conversion errors."""
    pass

class VideoConverter:
    """Handles video conversion with cropping using ffmpeg."""
    
    def __init__(
        self,
        output_format: str = 'mp4',
        codec: str = 'libx264',
        aspect_ratio: Optional[str] = None,
        max_dimension: Optional[int] = None,
        crf: int = 23,
        preset: str = 'medium',
        audio_codec: str = 'aac',
        audio_bitrate: str = '192k',
        overwrite: bool = False,
        dry_run: bool = False,
        crop_align_x: str = 'left',
        crop_align_y: str = 'top'
    ):
        """Initialize video converter with specified settings.
        
        Args:
            output_format: Output video format (e.g., 'mp4', 'mov')
            codec: Video codec (e.g., 'libx264', 'libx265')
            aspect_ratio: Target aspect ratio as 'W:H' (e.g., '16:9', '9:16', '1:1')
            max_dimension: Maximum width or height in pixels (larger dimension will be scaled to this)
            crf: Constant Rate Factor for quality (0-51, lower=better, default:23)
            preset: Encoding speed preset (ultrafast to veryslow, default:medium)
            audio_codec: Audio codec (default: 'aac')
            audio_bitrate: Audio bitrate (default: '192k')
            overwrite: If True, overwrite existing output files
            dry_run: If True, show commands without executing
            crop_align_x: Horizontal alignment within remaining area after edge removal ('left', 'center', 'right')
            crop_align_y: Vertical alignment within remaining area after edge removal ('top', 'center', 'bottom')
            
        Raises:
            ValueError: If aspect_ratio format is invalid or max_dimension is negative
        """
        self.output_format = output_format
        self.codec = codec
        self.aspect_ratio = self._parse_aspect_ratio(aspect_ratio) if aspect_ratio else None
        
        # Validate max_dimension
        if max_dimension is not None and max_dimension <= 0:
            raise ValueError(f"max_dimension must be positive, got {max_dimension}")
        self.max_dimension = max_dimension
        
        # Validate CRF range
        if not 0 <= crf <= 51:
            raise ValueError(f"CRF must be between 0 and 51, got {crf}")
        self.crf = crf
        
        self.preset = preset
        self.audio_codec = audio_codec
        self.audio_bitrate = audio_bitrate
        self.overwrite = overwrite
        self.dry_run = dry_run
        self.crop_align_x = crop_align_x.lower()
        self.crop_align_y = crop_align_y.lower()
    
    def _parse_aspect_ratio(self, aspect_str: str) -> Tuple[int, int]:
        """Parse aspect ratio string like '16:9' into tuple (16, 9).
        
        Args:
            aspect_str: Aspect ratio as 'W:H' (e.g., '16:9', '9:16', '4:3', '1:1')
            
        Returns:
            Tuple of (width_ratio, height_ratio)
            
        Raises:
            ValueError: If format is invalid or contains non-positive numbers
        """
        try:
            parts = aspect_str.split(':')
            if len(parts) != 2:
                raise ValueError(f"Invalid aspect ratio format: '{aspect_str}'. Expected format: 'W:H' (e.g., '16:9')")
            
            width, height = int(parts[0]), int(parts[1])
            
            if width <= 0 or height <= 0:
                raise ValueError(f"Aspect ratio dimensions must be positive, got {width}:{height}")
            
            return (width, height)
        except ValueError as e:
            if "invalid literal" in str(e).lower():
                raise ValueError(f"Invalid aspect ratio '{aspect_str}': must contain integers (e.g., '16:9', not '16.5:9')")
            raise
        
    def get_video_info(self, video_path: str) -> Dict:
        """Get video dimensions and metadata using ffprobe.
        
        Args:
            video_path: Path to video file
            
        Returns:
            Dictionary with keys: width, height, codec, duration
            
        Raises:
            subprocess.CalledProcessError: If ffprobe fails to run
            ValueError: If no video stream found or dimensions are invalid
            FileNotFoundError: If video file doesn't exist
        """
        # Validate file exists
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            video_path
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
            data = json.loads(result.stdout)
            
            # Find video stream
            video_stream = None
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    video_stream = stream
                    break
            
            if not video_stream:
                raise ValueError(f"No video stream found in {video_path}")
            
            # Validate dimensions
            width = int(video_stream.get('width', 0))
            height = int(video_stream.get('height', 0))
            
            if width <= 0 or height <= 0:
                raise ValueError(f"Invalid video dimensions: {width}x{height}")
            
            return {
                'width': width,
                'height': height,
                'codec': video_stream.get('codec_name', 'unknown'),
                'duration': float(video_stream.get('duration', 0)),
            }
        except subprocess.TimeoutExpired:
            raise ValueError(f"Timeout while reading video info for {video_path}")
        except subprocess.CalledProcessError as e:
            raise ValueError(f"Failed to get video info for {video_path}: {e.stderr}")
        except (json.JSONDecodeError, KeyError) as e:
            raise ValueError(f"Failed to parse video info for {video_path}: {e}")
    
    def parse_dimension(
        self, 
        value: Union[str, int, None], 
        reference: int, 
        is_size: bool = False
    ) -> int:
        """Parse dimension value as percentage of reference or absolute pixels.
        
        Args:
            value: Dimension value ('20%', 384, 'center', or None)
            reference: Reference dimension in pixels (e.g., video width/height)
            is_size: If True, parsing width/height; if False, parsing x/y position
        
        Returns:
            Absolute pixel value
            
        Raises:
            ValueError: If percentage exceeds 100% or value is invalid
            
        Examples:
            parse_dimension('20%', 1920, False) -> 384 (20% of 1920, for position)
            parse_dimension('50%', 1920, True) -> 960 (50% of 1920, for size)
            parse_dimension('center', 1920, False) -> 0 (centered, position handled by ffmpeg)
            parse_dimension(None, 1920, False) -> 0 (no offset)
        """
        if value is None:
            return 0 if not is_size else reference
        
        if isinstance(value, int):
            if value < 0:
                raise ValueError(f"Dimension cannot be negative: {value}")
            return value
        
        value = str(value).strip()
        
        # Handle 'center' keyword
        if value.lower() == 'center':
            if is_size:
                return reference  # Full dimension
            else:
                return 0  # Will be centered in ffmpeg crop filter
        
        # Handle percentage
        if value.endswith('%'):
            try:
                percent = float(value[:-1])
                if percent < 0:
                    raise ValueError(f"Percentage cannot be negative: {percent}%")
                if percent > 100:
                    raise ValueError(f"Percentage cannot exceed 100%: {percent}%")
                return int(reference * percent / 100)
            except ValueError as e:
                if "could not convert" in str(e).lower():
                    raise ValueError(f"Invalid percentage value: {value}")
                raise
        
        # Handle absolute value
        try:
            abs_value = int(value)
            if abs_value < 0:
                raise ValueError(f"Dimension cannot be negative: {abs_value}")
            return abs_value
        except ValueError:
            raise ValueError(f"Invalid dimension value: '{value}' (expected pixels, percentage, or 'center')")
    
    def calculate_output_dimensions(
        self, 
        orig_width: int, 
        orig_height: int
    ) -> Tuple[int, int]:
        """Calculate output dimensions based on aspect ratio and max dimension.
        
        Returns:
            Tuple of (output_width, output_height)
        """
        if not self.aspect_ratio:
            # No aspect ratio specified, keep original
            width, height = orig_width, orig_height
        else:
            # Calculate dimensions to fit aspect ratio
            target_aspect = self.aspect_ratio[0] / self.aspect_ratio[1]
            current_aspect = orig_width / orig_height
            
            if abs(current_aspect - target_aspect) < 0.01:
                # Already the right aspect ratio
                width, height = orig_width, orig_height
            else:
                # Use the original dimensions as a base and fit to aspect ratio
                # Prefer to match the larger dimension
                if orig_width > orig_height:
                    width = orig_width
                    height = int(width / target_aspect)
                else:
                    height = orig_height
                    width = int(height * target_aspect)
        
        # Apply max dimension - scale so the larger dimension equals max_dimension
        # This supports both upscaling and downscaling
        if self.max_dimension:
            if width > height:
                # Landscape or square: scale based on width
                scale = self.max_dimension / width
                width = self.max_dimension
                height = int(height * scale)
            else:
                # Portrait: scale based on height
                scale = self.max_dimension / height
                height = self.max_dimension
                width = int(width * scale)
        
        # Ensure dimensions are even (required for most codecs)
        width = width if width % 2 == 0 else width - 1
        height = height if height % 2 == 0 else height - 1
        
        return width, height
    
    def build_crop_filter(
        self,
        video_info: Dict,
        crop_x: Optional[Union[str, int]] = None,
        crop_y: Optional[Union[str, int]] = None,
        crop_width: Optional[Union[str, int]] = None,
        crop_height: Optional[Union[str, int]] = None,
    ) -> Optional[str]:
        """Build ffmpeg crop filter string.
        
        The crop filter format is: crop=out_w:out_h:x:y
        where x,y is the top-left corner of the crop area.
        
        Algorithm when aspect_ratio is set and crop edges are specified:
        1. Parse crop_x/crop_y as starting edges (e.g., 20% from left means x starts at 20% of width)
        2. Calculate available space from those edges
        3. Maximize crop size within available space while maintaining target aspect ratio
        """
        orig_width = video_info['width']
        orig_height = video_info['height']
        
        # If aspect ratio is specified but no explicit crop dimensions, auto-crop to aspect ratio
        if self.aspect_ratio and not any([crop_width, crop_height]):
            target_aspect = self.aspect_ratio[0] / self.aspect_ratio[1]
            
            # Calculate starting positions for crop boundaries
            # crop_x: how far from LEFT edge to start crop
            # crop_y: how far from TOP edge to start crop
            # (Future: could add crop_right, crop_bottom for cropping from those edges)
            
            if crop_x is not None and str(crop_x).lower() != 'center':
                x_start = self.parse_dimension(crop_x, orig_width, is_size=False)
            else:
                x_start = 0  # Default to left edge
            
            if crop_y is not None and str(crop_y).lower() != 'center':
                y_start = self.parse_dimension(crop_y, orig_height, is_size=False)
            else:
                y_start = 0  # Default to top edge
            
            # Calculate available dimensions from the starting edges
            available_width = orig_width - x_start
            available_height = orig_height - y_start
            
            # Maximize crop size while maintaining aspect ratio
            # Try using full available height first
            candidate_width = int(available_height * target_aspect)
            candidate_height = available_height
            
            # Check if this fits within available width
            if candidate_width > available_width:
                # Doesn't fit, use full available width instead
                candidate_width = available_width
                candidate_height = int(available_width / target_aspect)
            
            crop_width = candidate_width
            crop_height = candidate_height
            
            # Position the final crop within the available area based on alignment
            # Horizontal alignment
            if crop_x is not None and str(crop_x).lower() == 'center':
                crop_x = 'center'
            else:
                # Calculate position based on alignment within remaining area
                if self.crop_align_x == 'left':
                    crop_x = x_start
                elif self.crop_align_x == 'center':
                    crop_x = x_start + (available_width - crop_width) // 2
                elif self.crop_align_x == 'right':
                    crop_x = x_start + (available_width - crop_width)
                else:
                    crop_x = x_start  # Default to left
            
            # Vertical alignment
            if crop_y is not None and str(crop_y).lower() == 'center':
                crop_y = 'center'
            else:
                # Calculate position based on alignment within remaining area
                if self.crop_align_y == 'top':
                    crop_y = y_start
                elif self.crop_align_y == 'center':
                    crop_y = y_start + (available_height - crop_height) // 2
                elif self.crop_align_y == 'bottom':
                    crop_y = y_start + (available_height - crop_height)
                else:
                    crop_y = y_start  # Default to top
        
        # If still no crop specified, no cropping needed
        if all(v is None for v in [crop_x, crop_y, crop_width, crop_height]):
            return None
        
        # Parse dimensions if they weren't set by auto-crop logic
        if isinstance(crop_width, (str, int)):
            w = self.parse_dimension(crop_width, orig_width, is_size=True)
        else:
            w = crop_width if crop_width is not None else orig_width
            
        if isinstance(crop_height, (str, int)):
            h = self.parse_dimension(crop_height, orig_height, is_size=True)
        else:
            h = crop_height if crop_height is not None else orig_height
        
        # Ensure crop dimensions don't exceed original
        w = min(w, orig_width)
        h = min(h, orig_height)
        
        # Ensure dimensions are even (required for most codecs)
        w = w if w % 2 == 0 else w - 1
        h = h if h % 2 == 0 else h - 1
        
        # Parse positions
        x_val = crop_x if crop_x is not None else 0
        y_val = crop_y if crop_y is not None else 0
        
        # Handle 'center' positioning specially
        if str(x_val).lower() == 'center':
            x = f"(in_w-{w})/2"
        else:
            if isinstance(x_val, int):
                x = x_val
            else:
                x = self.parse_dimension(x_val, orig_width, is_size=False)
            # Ensure crop doesn't go out of bounds
            x = min(x, orig_width - w)
        
        if str(y_val).lower() == 'center':
            y = f"(in_h-{h})/2"
        else:
            if isinstance(y_val, int):
                y = y_val
            else:
                y = self.parse_dimension(y_val, orig_height, is_size=False)
            # Ensure crop doesn't go out of bounds
            y = min(y, orig_height - h)
        
        return f"crop={w}:{h}:{x}:{y}"
    
    def build_scale_filter(self, cropped_width: int, cropped_height: int) -> Optional[str]:
        """Build ffmpeg scale filter string based on output dimensions.
        
        Args:
            cropped_width: Width after cropping (or original if no crop)
            cropped_height: Height after cropping (or original if no crop)
        """
        output_width, output_height = self.calculate_output_dimensions(
            cropped_width, cropped_height
        )
        
        # Only scale if dimensions changed
        if output_width == cropped_width and output_height == cropped_height:
            return None
        
        return f"scale={output_width}:{output_height}"
    
    def convert_video(
        self,
        input_path: Path,
        output_path: Path,
        crop_x: Optional[Union[str, int]] = None,
        crop_y: Optional[Union[str, int]] = None,
        crop_width: Optional[Union[str, int]] = None,
        crop_height: Optional[Union[str, int]] = None,
    ) -> bool:
        """Convert a single video file.
        
        Args:
            input_path: Input video file path
            output_path: Output video file path
            crop_x: How far from LEFT edge to start crop (e.g., '20%' removes left 20%)
            crop_y: How far from TOP edge to start crop (e.g., '10%' removes top 10%)
            crop_width: Explicit crop width (overrides aspect ratio auto-crop)
            crop_height: Explicit crop height (overrides aspect ratio auto-crop)
        
        Returns:
            True if conversion succeeded, False if failed
            
        Notes:
            - Logs detailed progress and filter settings
            - In dry-run mode, shows command without executing
            - Gracefully handles errors and continues processing
        """
        try:
            # Skip if output exists and not overwriting
            if output_path.exists() and not self.overwrite and not self.dry_run:
                logger.warning(f"  Skipping (output exists): {output_path.name}")
                return True
            # Get video info
            video_info = self.get_video_info(str(input_path))
            orig_width = video_info['width']
            orig_height = video_info['height']
            
            logger.info(
                f"Processing {input_path.name}: {orig_width}x{orig_height}"
            )
            
            # Build filter chain
            filters = []
            
            crop_filter = self.build_crop_filter(
                video_info, crop_x, crop_y, crop_width, crop_height
            )
            
            # Determine dimensions after crop for scale calculation
            if crop_filter:
                filters.append(crop_filter)
                logger.info(f"  Crop filter: {crop_filter}")
                
                # Extract crop dimensions from filter
                # Format is crop=w:h:x:y
                parts = crop_filter.split('=')[1].split(':')
                cropped_width = int(parts[0])
                cropped_height = int(parts[1])
            else:
                cropped_width = orig_width
                cropped_height = orig_height
            
            scale_filter = self.build_scale_filter(cropped_width, cropped_height)
            if scale_filter:
                filters.append(scale_filter)
                logger.info(f"  Scale filter: {scale_filter}")
            
            # Show final output dimensions
            if self.aspect_ratio or self.max_dimension:
                final_width, final_height = self.calculate_output_dimensions(
                    cropped_width, cropped_height
                )
                logger.info(f"  Output dimensions: {final_width}x{final_height}")
                if self.aspect_ratio:
                    logger.info(f"  Target aspect ratio: {self.aspect_ratio[0]}:{self.aspect_ratio[1]}")
            
            # Build ffmpeg command
            cmd = ['ffmpeg']
            
            if self.overwrite:
                cmd.append('-y')
            else:
                cmd.append('-n')
            
            cmd.extend(['-i', str(input_path)])
            
            # Add filters
            if filters:
                cmd.extend(['-vf', ','.join(filters)])
            
            # Video codec settings
            cmd.extend(['-c:v', self.codec])
            
            if self.codec in ['libx264', 'libx265']:
                cmd.extend(['-crf', str(self.crf)])
                cmd.extend(['-preset', self.preset])
            
            # Audio settings
            cmd.extend(['-c:a', self.audio_codec])
            cmd.extend(['-b:a', self.audio_bitrate])
            
            # Output
            cmd.append(str(output_path))
            
            logger.info(f"  Output: {output_path}")
            
            if self.dry_run:
                logger.info(f"  [DRY RUN] Command: {' '.join(cmd)}")
                return True
            
            # Execute ffmpeg command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=3600  # 1 hour timeout for long videos
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip()
                logger.error(f"  Failed: {error_msg}")
                # Check for common error patterns
                if "Invalid data found" in error_msg:
                    logger.error(f"  Likely cause: Corrupted or unsupported video format")
                elif "No such file or directory" in error_msg:
                    logger.error(f"  Likely cause: Output path invalid or inaccessible")
                elif "codec" in error_msg.lower():
                    logger.error(f"  Likely cause: Codec issue - try different codec with --codec")
                return False
            
            # Verify output was created
            if not output_path.exists():
                logger.error(f"  Failed: Output file was not created")
                return False
                
            # Verify output has non-zero size
            if output_path.stat().st_size == 0:
                logger.error(f"  Failed: Output file is empty")
                output_path.unlink()  # Delete empty file
                return False
            
            logger.info(f"  ✓ Converted successfully")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error(f"  Error: Conversion timed out after 1 hour for {input_path.name}")
            return False
        except ValueError as e:
            logger.error(f"  Error: Invalid parameters - {e}")
            return False
        except FileNotFoundError as e:
            logger.error(f"  Error: File not found - {e}")
            return False  
        except PermissionError as e:
            logger.error(f"  Error: Permission denied - {e}")
            return False
        except Exception as e:
            logger.error(f"  Error converting {input_path.name}: {type(e).__name__}: {e}")
            return False
    
    def process_directory(
        self,
        input_dir: Path,
        output_dir: Path,
        crop_x: Optional[Union[str, int]] = None,
        crop_y: Optional[Union[str, int]] = None,
        crop_width: Optional[Union[str, int]] = None,
        crop_height: Optional[Union[str, int]] = None,
        recursive: bool = False,
    ) -> Tuple[int, int]:
        """Process all videos in a directory.
        
        Args:
            input_dir: Directory containing input videos
            output_dir: Directory for output videos
            crop_x: X offset for crop
            crop_y: Y offset for crop  
            crop_width: Width of crop
            crop_height: Height of crop
            recursive: If True, process subdirectories recursively
            
        Returns:
            Tuple of (successful_count, failed_count)
            
        Raises:
            FileNotFoundError: If input_dir doesn't exist
            PermissionError: If output_dir cannot be created
        """
        # Validate input directory
        if not input_dir.exists():
            raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
        if not input_dir.is_dir():
            raise NotADirectoryError(f"Input path is not a directory: {input_dir}")
            
        # Find all video files
        if recursive:
            video_files = []
            for ext in VIDEO_EXTENSIONS:
                video_files.extend(input_dir.rglob(f"*{ext}"))
        else:
            video_files = [
                f for f in input_dir.iterdir()
                if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
            ]
        
        if not video_files:
            logger.warning(f"No video files found in {input_dir}")
            logger.info(f"Supported formats: {', '.join(sorted(VIDEO_EXTENSIONS))}")
            return 0, 0
        
        logger.info(f"Found {len(video_files)} video file(s)")
        
        # Create output directory
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionError(f"Cannot create output directory {output_dir}: {e}")
        
        # Process each video
        successful = 0
        failed = 0
        
        for i, video_file in enumerate(sorted(video_files), 1):
            logger.info(f"[{i}/{len(video_files)}] Processing: {video_file.name}")
            
            # Preserve directory structure if recursive
            if recursive:
                rel_path = video_file.relative_to(input_dir)
                output_path = output_dir / rel_path.parent / f"{rel_path.stem}.{self.output_format}"
                try:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                except PermissionError as e:
                    logger.error(f"  Cannot create output subdirectory: {e}")
                    failed += 1
                    continue
            else:
                output_path = output_dir / f"{video_file.stem}.{self.output_format}"
            
            if self.convert_video(
                video_file, 
                output_path,
                crop_x=crop_x,
                crop_y=crop_y,
                crop_width=crop_width,
                crop_height=crop_height
            ):
                successful += 1
            else:
                failed += 1
        
        # Summary
        logger.info(f"\n{'='*60}")
        logger.info(f"Conversion complete: {successful} succeeded, {failed} failed")
        logger.info(f"{'='*60}")
        
        return successful, failed


def check_ffmpeg_installed() -> bool:
    """Check if ffmpeg is installed and available."""
    try:
        subprocess.run(
            ['ffmpeg', '-version'], 
            capture_output=True, 
            check=True,
            timeout=5
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def check_homebrew_installed() -> bool:
    """Check if Homebrew is installed (macOS)."""
    try:
        subprocess.run(
            ['brew', '--version'], 
            capture_output=True, 
            check=True,
            timeout=5
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def install_ffmpeg_with_brew() -> bool:
    """Attempt to install ffmpeg using Homebrew."""
    logger.info("Attempting to install ffmpeg using Homebrew...")
    try:
        result = subprocess.run(
            ['brew', 'install', 'ffmpeg'],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout for installation
        )
        if result.returncode == 0:
            logger.info("✓ ffmpeg installed successfully")
            return True
        else:
            logger.error(f"Failed to install ffmpeg: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        logger.error("Installation timed out")
        return False
    except Exception as e:
        logger.error(f"Error during installation: {e}")
        return False


def check_and_install_ffmpeg(auto_install: bool = False) -> bool:
    """Check for ffmpeg and offer to install if missing.
    
    Args:
        auto_install: If True, install without prompting (requires Homebrew on macOS)
    
    Returns:
        True if ffmpeg is available (or was successfully installed)
        False if ffmpeg is not available and could not be installed
    """
    # Check if already installed
    if check_ffmpeg_installed():
        return True
    
    logger.warning("ffmpeg not found")
    
    # Check platform
    import platform
    system = platform.system()
    
    if system == 'Darwin':  # macOS
        if not check_homebrew_installed():
            logger.error(
                "Homebrew is not installed. Install it from https://brew.sh/ "
                "or install ffmpeg manually."
            )
            return False
        
        # Auto-install or ask user
        if auto_install:
            logger.info("Auto-installing ffmpeg...")
            if install_ffmpeg_with_brew():
                return check_ffmpeg_installed()
            return False
        
        # Ask user if they want to install
        try:
            response = input("Would you like to install ffmpeg now using Homebrew? (y/n): ").strip().lower()
            if response in ['y', 'yes']:
                if install_ffmpeg_with_brew():
                    return check_ffmpeg_installed()
                return False
            else:
                logger.info("Installation cancelled. Please install ffmpeg manually.")
                return False
        except (EOFError, KeyboardInterrupt):
            logger.info("\nInstallation cancelled")
            return False
    
    elif system == 'Linux':
        logger.error(
            "Please install ffmpeg using your package manager:\n"
            "  Ubuntu/Debian: sudo apt-get install ffmpeg\n"
            "  Fedora: sudo dnf install ffmpeg\n"
            "  Arch: sudo pacman -S ffmpeg"
        )
        return False
    
    elif system == 'Windows':
        logger.error(
            "Please install ffmpeg from https://ffmpeg.org/download.html\n"
            "Or use a package manager like Chocolatey: choco install ffmpeg"
        )
        return False
    
    else:
        logger.error("Please install ffmpeg manually for your platform")
        return False


def main():
    """Main entry point for the video converter CLI.
    
    Handles argument parsing, validation, ffmpeg availability check,
    and orchestrates the conversion process.
    
    Exit codes:
        0: Success
        1: Error (missing dependencies, no files found, conversion failures, etc.)
        2: Invalid arguments
    """
    parser = argparse.ArgumentParser(
        description='Convert videos with optional cropping using ffmpeg',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert all videos to 9:16 vertical format for TikTok/Reels
  python video_converter.py /path/to/videos --aspect-ratio 9:16 --max-dimension 1920
  
  # Remove left 20% and create 9:16 crop aligned left
  python video_converter.py /path/to/videos --aspect-ratio 9:16 --crop-x 20% --crop-align-x left
  
  # Create centered 16:9 crop without edge removal
  python video_converter.py /path/to/videos --aspect-ratio 16:9 --crop-align-x center --crop-align-y center
  
  # Dry run to preview commands
  python video_converter.py /path/to/videos --aspect-ratio 4:3 --dry-run

Supported formats: """ + ", ".join(sorted(VIDEO_EXTENSIONS))
    )
    
    # Input/Output
    parser.add_argument(
        'input_dir',
        type=str,
        help='Directory containing videos to convert'
    )
    parser.add_argument(
        '--output-dir', '-o',
        type=str,
        default=None,
        help='Output directory (default: <input_dir>_converted)'
    )
    parser.add_argument(
        '--recursive', '-r',
        action='store_true',
        help='Process subdirectories recursively'
    )
    
    # Cropping options
    crop_group = parser.add_argument_group('cropping options')
    crop_group.add_argument(
        '--crop-x',
        type=str,
        default=None,
        help='How far from LEFT edge to start cropping (e.g., "20%%" removes left 20%%)'
    )
    crop_group.add_argument(
        '--crop-y',
        type=str,
        default=None,
        help='How far from TOP edge to start cropping (e.g., "10%%" removes top 10%%)'
    )
    crop_group.add_argument(
        '--crop-align-x',
        type=str,
        choices=['left', 'center', 'right'],
        default='left',
        help='Horizontal alignment of final crop within remaining area (default: left)'
    )
    crop_group.add_argument(
        '--crop-align-y',
        type=str,
        choices=['top', 'center', 'bottom'],
        default='top',
        help='Vertical alignment of final crop within remaining area (default: top)'
    )
    crop_group.add_argument(
        '--crop-width',
        type=str,
        default=None,
        help='Crop width (e.g., "60%%", "1920")'
    )
    crop_group.add_argument(
        '--crop-height',
        type=str,
        default=None,
        help='Crop height (e.g., "100%%", "1080")'
    )
    
    # Output format
    format_group = parser.add_argument_group('output format options')
    format_group.add_argument(
        '--format', '-f',
        type=str,
        default='mp4',
        help='Output format (default: mp4)'
    )
    format_group.add_argument(
        '--codec', '-c',
        type=str,
        default='libx264',
        help='Video codec (default: libx264)'
    )
    format_group.add_argument(
        '--aspect-ratio', '-a',
        type=str,
        default=None,
        help='Target aspect ratio (e.g., "16:9", "4:3", "1:1", "9:16"). Auto-crops and scales to fit.'
    )
    format_group.add_argument(
        '--max-dimension',
        type=int,
        default=None,
        help='Maximum dimension (width or height) for output, preserving aspect ratio (e.g., 1080, 1920)'
    )
    format_group.add_argument(
        '--crf',
        type=int,
        default=23,
        help='Constant Rate Factor for quality (lower=better, 18-28 typical, default: 23)'
    )
    format_group.add_argument(
        '--preset',
        type=str,
        default='medium',
        choices=['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 
                 'medium', 'slow', 'slower', 'veryslow'],
        help='Encoding preset (default: medium)'
    )
    format_group.add_argument(
        '--audio-codec',
        type=str,
        default='aac',
        help='Audio codec (default: aac)'
    )
    format_group.add_argument(
        '--audio-bitrate',
        type=str,
        default='192k',
        help='Audio bitrate (default: 192k)'
    )
    
    # Behavior
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Overwrite existing output files'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without actually converting'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    parser.add_argument(
        '--auto-install-deps',
        action='store_true',
        help='Automatically install missing dependencies without prompting (requires Homebrew on macOS)'
    )
    
    args = parser.parse_args()
    
    # Configure logging level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")
    
    # Validate and resolve input directory
    try:
        input_dir = Path(args.input_dir).resolve()
        if not input_dir.exists():
            logger.error(f"Input directory does not exist: {input_dir}")
            sys.exit(2)
        if not input_dir.is_dir():
            logger.error(f"Input path is not a directory: {input_dir}")
            sys.exit(2)
    except Exception as e:
        logger.error(f"Invalid input directory path: {e}")
        sys.exit(2)
    
    # Determine and validate output directory
    try:
        if args.output_dir:
            output_dir = Path(args.output_dir).resolve()
        else:
            output_dir = Path(f"{input_dir}_converted")
        
        # Check if output directory is writable (if it exists) or parent is writable (if it doesn't)
        test_dir = output_dir if output_dir.exists() else output_dir.parent
        if not os.access(test_dir, os.W_OK):
            logger.error(f"Output directory is not writable: {output_dir}")
            sys.exit(2)
            
    except Exception as e:
        logger.error(f"Invalid output directory path: {e}")
        sys.exit(2)
    
    logger.info(f"Input directory: {input_dir}")
    logger.info(f"Output directory: {output_dir}")
    
    # Check ffmpeg availability and offer to install if missing
    if not check_and_install_ffmpeg(auto_install=args.auto_install_deps):
        logger.error("ffmpeg is required but not available. Exiting.")
        sys.exit(1)
    
    # Create converter with validation
    try:
        converter = VideoConverter(
            output_format=args.format,
            codec=args.codec,
            aspect_ratio=args.aspect_ratio,
            max_dimension=args.max_dimension,
            crf=args.crf,
            preset=args.preset,
            audio_codec=args.audio_codec,
            audio_bitrate=args.audio_bitrate,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
            crop_align_x=args.crop_align_x,
            crop_align_y=args.crop_align_y,
        )
    except ValueError as e:
        logger.error(f"Invalid configuration: {e}")
        sys.exit(2)
    
    # Process directory with error handling
    try:
        successful, failed = converter.process_directory(
            input_dir,
            output_dir,
            crop_x=args.crop_x,
            crop_y=args.crop_y,
            crop_width=args.crop_width,
            crop_height=args.crop_height,
            recursive=args.recursive,
        )
    except KeyboardInterrupt:
        logger.info("\n\nConversion interrupted by user")
        sys.exit(1)
    except PermissionError as e:
        logger.error(f"Permission denied: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error during processing: {type(e).__name__}: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    
    # Exit with appropriate code
    if successful == 0 and failed == 0:
        logger.warning("No videos were processed")
        sys.exit(1)
    elif failed > 0:
        logger.warning(f"Completed with {failed} failure(s)")
        sys.exit(1)
    else:
        logger.info("All conversions completed successfully!")
        sys.exit(0)


if __name__ == '__main__':
    main()

import argparse
import os
import re
import subprocess
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def calculate_resulting_length(silence_starts, silence_ends, duration_sec, pad_sec):
    """
    Calculate the resulting video length after removing silence segments with given padding.
    
    Args:
        silence_starts: List of silence start times
        silence_ends: List of silence end times
        duration_sec: Original video duration
        pad_sec: Padding value in seconds
    
    Returns:
        Total duration of segments that would be kept
    """
    if len(silence_starts) != len(silence_ends):
        if len(silence_starts) > len(silence_ends):
            silence_ends = list(silence_ends) + [duration_sec]
        else:
            # This shouldn't happen, but handle it
            silence_ends = list(silence_ends)
    
    segments_to_keep = []
    prev_end = 0.0
    
    for silence_start, silence_end in zip(silence_starts, silence_ends):
        # Skip silence that's too short to trim
        if silence_end - silence_start <= pad_sec * 2:
            continue
        if silence_start > prev_end:
            segment_start = round(prev_end, 3)
            segment_end = round(silence_start + pad_sec, 3)
            segments_to_keep.append((segment_start, segment_end))
        prev_end = max(0, silence_end - pad_sec)
    
    if prev_end < duration_sec:
        segments_to_keep.append((round(prev_end, 3), round(duration_sec, 3)))
    
    # Calculate total duration
    total_duration = sum(end - start for start, end in segments_to_keep)
    return total_duration


def find_optimal_padding(silence_starts, silence_ends, duration_sec, target_length):
    """
    Find the optimal padding value to reach or get just below target length.
    
    Args:
        silence_starts: List of silence start times
        silence_ends: List of silence end times
        duration_sec: Original video duration
        target_length: Target video length in seconds
    
    Returns:
        Optimal padding value in seconds
    """
    if not silence_starts:
        # No silence detected, cannot reduce video length
        return 0.0
    
    # Check edge cases
    result_with_0_pad = calculate_resulting_length(silence_starts, silence_ends, duration_sec, 0.0)
    
    if target_length >= duration_sec:
        # Target is longer than or equal to original - cannot reach target
        return 0.0
    
    if result_with_0_pad > target_length:
        # Even with 0 padding, result is longer than target - cannot shorten further
        return 0.0
    
    # If result_with_0_pad < target_length, we can increase padding to reach closer to target
    
    # Iterate through padding values starting from 0, incrementing by 10ms (0.01s)
    max_pad = 10.0  # Safety limit: 10 seconds max padding
    pad_increment = 0.01  # 10ms increments
    
    current_pad = 0.0
    best_pad = 0.0
    best_result = result_with_0_pad
    
    while current_pad <= max_pad:
        resulting_length = calculate_resulting_length(silence_starts, silence_ends, duration_sec, current_pad)
        
        # If we're strictly below target, this is a candidate
        if resulting_length < target_length:
            best_pad = current_pad
            best_result = resulting_length
        else:
            # If we've reached or exceeded target, stop - use the previous value (just below target)
            break
        
        current_pad += pad_increment
    
    return round(best_pad, 3)

parser = argparse.ArgumentParser(
    description='Remove silence segments from video file',
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
Examples:
  uv run python remove_silence.py video.mkv --output-dir ./output
  uv run python remove_silence.py video.mkv -o ./output
  uv run python remove_silence.py video.mkv -o ./output --target-length 120
  
Configuration is loaded from .env file:
  NOISE_THRESHOLD=-30.0
  MIN_DURATION=0.5
  PAD=0.5
  
When --target-length is specified, it automatically calculates the optimal
padding value (starting from 0ms, incrementing by 10ms) to reach or get
just below the target video length. This overrides the PAD value from .env.
        """
)
parser.add_argument('input_file', help='Input video file')
parser.add_argument('-o', '--output-dir', default='.', 
                    help='Output directory (default: current directory)')
parser.add_argument('--target-length', type=float, default=None,
                    help='Target video length in seconds. Automatically calculates optimal padding to reach this length.')
args = parser.parse_args()

input_file = args.input_file
output_dir = args.output_dir

# Load configuration from .env file with defaults
noise_threshold = float(os.getenv('NOISE_THRESHOLD', '-30.0'))
min_duration = float(os.getenv('MIN_DURATION', '0.5'))
PAD_SEC = float(os.getenv('PAD', '0.5'))

# Get basename and extension from input file
basename = os.path.splitext(os.path.basename(input_file))[0]
extension = os.path.splitext(input_file)[1] or '.mp4'

# Create output directory if it doesn't exist
os.makedirs(output_dir, exist_ok=True)

# Build output file path
output_file = os.path.join(output_dir, f"{basename}{extension}")

# --- detect silence ---
silence_filter = f"silencedetect=n={noise_threshold}dB:d={min_duration}"
result = subprocess.run(
    ["ffmpeg", "-y", "-i", input_file, "-af", silence_filter, "-f", "null", "-"],
    stderr=subprocess.PIPE, text=True
).stderr

silence_starts = [float(x) for x in re.findall(r"silence_start: (\d+\.?\d*)", result)]
silence_ends   = [float(x) for x in re.findall(r"silence_end: (\d+\.?\d*)", result)]

# --- get duration, bitrate, and resolution ---
# Get duration from format
duration_result = subprocess.run(
    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
     "-of", "default=nw=1:nk=1", input_file],
    capture_output=True, text=True
).stdout.strip()
duration_sec = float(duration_result) if duration_result else 0.0

# Get video resolution and bitrate
probe = subprocess.run(
    ["ffprobe", "-v", "error", "-select_streams", "v:0",
     "-show_entries", "stream=width,height,bit_rate",
     "-of", "default=nw=1:nk=1", input_file],
    capture_output=True, text=True
).stdout.strip().split('\n')

video_width = probe[0] if len(probe) > 0 else "1080"
video_height = probe[1] if len(probe) > 1 else "1920"
# Try to get bitrate, use format bitrate if stream bitrate not available
format_probe = subprocess.run(
    ["ffprobe", "-v", "error", "-show_entries", "format=bit_rate",
     "-of", "default=nw=1:nk=1", input_file],
    capture_output=True, text=True
).stdout.strip()
bitrate_bps = int(format_probe) if format_probe else 3000000  # Default 3Mbps

if len(silence_starts) > len(silence_ends):
    silence_ends.append(duration_sec)

# If target length is specified, calculate optimal padding
if args.target_length is not None:
    optimal_pad = find_optimal_padding(silence_starts, silence_ends, duration_sec, args.target_length)
    PAD_SEC = optimal_pad
    resulting_length = calculate_resulting_length(silence_starts, silence_ends, duration_sec, PAD_SEC)
    print(f"Target length: {args.target_length}s")
    print(f"Calculated optimal padding: {PAD_SEC}s")
    print(f"Expected resulting length: {resulting_length:.3f}s")
    if resulting_length > args.target_length:
        print(f"Warning: Resulting length ({resulting_length:.3f}s) exceeds target ({args.target_length}s)")
    elif resulting_length < args.target_length:
        diff = args.target_length - resulting_length
        print(f"Note: Resulting length ({resulting_length:.3f}s) is {diff:.3f}s below target ({args.target_length}s)")

segments_to_keep = []
prev_end = 0.0

for silence_start, silence_end in zip(silence_starts, silence_ends):
    # skip silence that's too short to trim
    if silence_end - silence_start <= PAD_SEC * 2:
        continue
    if silence_start > prev_end:
        segment_start = round(prev_end, 3)
        segment_end   = round(silence_start + PAD_SEC, 3)
        segments_to_keep.append((segment_start, segment_end))
    prev_end = max(0, silence_end - PAD_SEC)

if prev_end < duration_sec:
    segments_to_keep.append((round(prev_end, 3), round(duration_sec, 3)))

# --- build FFmpeg filter chain ---
filter_chains = ''.join(
    f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}];"
    f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}];"
    for i, (s, e) in enumerate(segments_to_keep)
)
concat_inputs = ''.join(f"[v{i}][a{i}]" for i in range(len(segments_to_keep)))
filter_complex = f"{filter_chains}{concat_inputs}concat=n={len(segments_to_keep)}:v=1:a=1[outv][outa]"

# --- choose hardware encoder if available ---
available_encoders = subprocess.run(
    ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True
).stdout
preferred_codecs = ["h264_nvenc", "h264_qsv", "h264_vaapi", "h264_videotoolbox", "h264_amf"]
video_codec = next((c for c in preferred_codecs if c in available_encoders), "libx264")

# --- run FFmpeg ---
cmd = [
    "ffmpeg", "-y", "-i", input_file,
    "-filter_complex", filter_complex,
    "-map", "[outv]", "-map", "[outa]",
    "-c:v", video_codec, "-b:v", str(bitrate_bps),
    "-c:a", "aac", "-b:a", "192k", output_file
]

print(f"Input: {input_file}")
print(f"Output: {output_file}")
print(f"Settings: noise={noise_threshold}dB, min_duration={min_duration}s, pad={PAD_SEC}s")
print(f"Filter complex length: {len(filter_complex)} characters")
print(f"Number of segments: {len(segments_to_keep)}")
print(f"Running FFmpeg command...")
subprocess.run(cmd, check=True)
print(f"Done! Output saved to: {output_file}")

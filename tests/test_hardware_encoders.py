"""Diagnostic script to test hardware encoder availability.

Lists all hardware encoders and tests each one to see which work.
"""

import subprocess
import sys


# Hardware encoders to test
HARDWARE_ENCODERS = [
    ("hevc_qsv", "Intel Quick Sync HEVC", [
        "-preset", "slow",
        "-global_quality", "20",
    ]),
    ("hevc_amf", "AMD AMF HEVC", []),
    ("hevc_nvenc", "NVIDIA NVENC HEVC", [
        "-preset", "slow",
        "-cq", "24",
    ]),
    ("h264_qsv", "Intel Quick Sync H.264", [
        "-preset", "slow",
        "-global_quality", "23",
    ]),
    ("h264_amf", "AMD AMF H.264", []),
    ("h264_nvenc", "NVIDIA NVENC H.264", [
        "-preset", "slow",
        "-cq", "23",
    ]),
]

SOFTWARE_ENCODERS = [
    ("libx265", "Software HEVC (x265)", [
        "-crf", "24",
        "-preset", "slow",
    ]),
    ("libx264", "Software H.264 (x264)", [
        "-crf", "23",
        "-preset", "slow",
    ]),
]


def _test_encoder(codec: str, args: list[str]) -> tuple[bool, str]:
    """Test if an encoder works. Returns (success, error_message)."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-v", "error",
        "-f", "lavfi",
        "-i", "testsrc=duration=1:size=320x240",  # Use testsrc - more compatible with HW encoders
        "-frames:v", "25",
        "-c:v", codec,
        "-pix_fmt", "yuv420p",
    ] + args + ["-f", "null", "-"]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return True, ""
        else:
            # Extract useful error info
            err = result.stderr.strip()
            if "not found" in err.lower() or "unknown encoder" in err.lower():
                return False, "Not available"
            elif "error" in err.lower():
                # Get first error line
                first_error = [line for line in err.split('\n') if 'error' in line.lower()][:1]
                return False, first_error[0] if first_error else "Failed"
            return False, "Failed"
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except FileNotFoundError:
        return False, "FFmpeg not found"
    except Exception as e:
        return False, str(e)


def list_all_encoders():
    """Get list of all encoders from FFmpeg."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            # Filter for video encoders
            encoders = []
            for line in result.stdout.split('\n'):
                if line.strip().startswith('V'):
                    parts = line.split()
                    if len(parts) >= 2:
                        encoders.append(parts[1])
            return encoders
    except:
        pass
    return []


def main():
    print("=" * 70)
    print("HARDWARE ENCODER DIAGNOSTIC")
    print("=" * 70)
    print()
    
    # List all available encoders
    print("Step 1: Listing all video encoders from FFmpeg...")
    all_encoders = list_all_encoders()
    hardware_found = [e for e, _, _ in HARDWARE_ENCODERS if e in all_encoders]
    
    print(f"Found {len(all_encoders)} total video encoders")
    if hardware_found:
        print(f"Hardware encoders listed: {', '.join(hardware_found)}")
    else:
        print("No hardware encoders found")
    print()
    
    # Test hardware encoders
    print("Step 2: Testing hardware encoders...")
    print("-" * 70)
    working_hardware = []
    
    for codec, name, args in HARDWARE_ENCODERS:
        print(f"\nTesting {name} ({codec})...")
        if codec not in all_encoders:
            print(f"  [NOT LISTED] - Not available in this FFmpeg build")
            continue
            
        success, error = _test_encoder(codec, args)
        if success:
            print(f"  [✓ WORKING] - Hardware encoder ready!")
            working_hardware.append((codec, name))
        else:
            print(f"  [✗ FAILED] - {error}")
    
    print()
    print("-" * 70)
    print()
    
    # Test software encoders
    print("Step 3: Testing software encoders (fallback)...")
    print("-" * 70)
    working_software = []
    
    for codec, name, args in SOFTWARE_ENCODERS:
        print(f"\nTesting {name} ({codec})...")
        if codec not in all_encoders:
            print(f"  [NOT LISTED] - Not available")
            continue
            
        success, error = _test_encoder(codec, args)
        if success:
            print(f"  [✓ WORKING] - Software encoder ready")
            working_software.append((codec, name))
        else:
            print(f"  [✗ FAILED] - {error}")
    
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    if working_hardware:
        print(f"\n✓ Working hardware encoders ({len(working_hardware)}):")
        for codec, name in working_hardware:
            print(f"  - {name} ({codec})")
    else:
        print("\n✗ No hardware encoders working")
    
    if working_software:
        print(f"\n✓ Working software encoders ({len(working_software)}):")
        for codec, name in working_software:
            print(f"  - {name} ({codec})")
    
    print()
    print("Recommendation:")
    if working_hardware:
        best = working_hardware[0]
        print(f"  Use hardware encoder: {best[1]} ({best[0]})")
    elif working_software:
        best = working_software[0]
        print(f"  Use software encoder: {best[1]} ({best[0]})")
    else:
        print("  ERROR: No working encoders found!")
    
    print()
    print("=" * 70)
    
    return 0 if (working_hardware or working_software) else 1


if __name__ == "__main__":
    sys.exit(main())

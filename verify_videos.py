import json
import subprocess
import sqlite3
import os
from datetime import datetime

# Database connection
db_path = "/var/lib/media-manager/database.db"
storage_path = "/var/lib/media-manager/storage/video/ihya"
report_path = "/tmp/video_check_report.txt"

def run_ffprobe(video_path):
    """Run ffprobe and return parsed JSON output"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_format", "-show_streams",
        "-print_format", "json",
        video_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None, result.stderr
        return json.loads(result.stdout), None
    except subprocess.TimeoutExpired:
        return None, "FFprobe timeout (30s)"
    except Exception as e:
        return None, str(e)

def check_video(video_id, db_duration, db_title, db_file_size):
    """Check a single video file"""
    video_path = os.path.join(storage_path, f"{video_id}.mp4")
    
    # Check if file exists
    if not os.path.exists(video_path):
        return {
            "id": video_id,
            "title": db_title[:50],
            "status": "ERROR",
            "errors": ["File not found"],
            "db_duration": db_duration,
            "ffprobe_duration": None,
            "codec": None,
            "resolution": None,
            "file_size_match": False
        }
    
    # Get actual file size
    actual_size = os.path.getsize(video_path)
    
    # Run ffprobe
    probe_data, error = run_ffprobe(video_path)
    
    if error:
        return {
            "id": video_id,
            "title": db_title[:50],
            "status": "ERROR",
            "errors": [f"FFprobe failed: {error}"],
            "db_duration": db_duration,
            "ffprobe_duration": None,
            "codec": None,
            "resolution": None,
            "file_size_match": actual_size == db_file_size
        }
    
    errors = []
    warnings = []
    
    # Find video stream
    video_stream = None
    for stream in probe_data.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
            break
    
    if not video_stream:
        errors.append("No video stream found")
    else:
        # Check codec
        codec = video_stream.get("codec_name", "unknown")
        if codec not in ["hevc", "h265"]:
            errors.append(f"Video codec is {codec}, expected hevc/h265")
        
        # Check resolution
        width = video_stream.get("width")
        height = video_stream.get("height")
        resolution = f"{width}x{height}" if width and height else "unknown"
        
        # Check for common resolution issues
        if height and height < 720:
            warnings.append(f"Low resolution: {resolution}")
    
    # Check duration
    format_data = probe_data.get("format", {})
    ffprobe_duration = None
    try:
        ffprobe_duration = float(format_data.get("duration", 0))
        duration_diff = abs(ffprobe_duration - db_duration)
        if duration_diff > 2:  # Allow 2 second tolerance
            errors.append(f"Duration mismatch: ffprobe={ffprobe_duration:.1f}s, db={db_duration}s (diff={duration_diff:.1f}s)")
    except (ValueError, TypeError):
        errors.append("Could not parse duration from ffprobe")
    
    # Check for format errors
    format_errors = format_data.get("tags", {}).get("error", None)
    if format_errors:
        errors.append(f"Format error: {format_errors}")
    
    # Determine status
    if errors:
        status = "ERROR"
    elif warnings:
        status = "WARNING"
    else:
        status = "OK"
    
    return {
        "id": video_id,
        "title": db_title[:50],
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "db_duration": db_duration,
        "ffprobe_duration": ffprobe_duration,
        "codec": video_stream.get("codec_name") if video_stream else None,
        "resolution": resolution if video_stream else None,
        "file_size_match": actual_size == db_file_size,
        "actual_size": actual_size,
        "db_size": db_file_size
    }

def main():
    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all videos
    cursor.execute('SELECT id, title, duration, file_size FROM files WHERE type = "video" ORDER BY id')
    videos = cursor.fetchall()
    conn.close()
    
    results = []
    error_count = 0
    warning_count = 0
    ok_count = 0
    
    print(f"Checking {len(videos)} videos...")
    print("=" * 80)
    
    for i, (video_id, title, duration, file_size) in enumerate(videos, 1):
        result = check_video(video_id, duration, title, file_size)
        results.append(result)
        
        if result["status"] == "OK":
            ok_count += 1
            print(f"[{i}/{len(videos)}] OK: {video_id[:40]}...")
        elif result["status"] == "WARNING":
            warning_count += 1
            print(f"[{i}/{len(videos)}] WARNING: {video_id[:40]}... - {', '.join(result['warnings'])}")
        else:
            error_count += 1
            print(f"[{i}/{len(videos)}] ERROR: {video_id[:40]}... - {', '.join(result['errors'])}")
    
    # Generate report
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("VIDEO FILE VERIFICATION REPORT")
    report_lines.append(f"Generated: {datetime.now().isoformat()}")
    report_lines.append(f"Total videos checked: {len(videos)}")
    report_lines.append("=" * 80)
    report_lines.append("")
    
    # Summary
    report_lines.append("SUMMARY")
    report_lines.append("-" * 40)
    report_lines.append(f"OK:       {ok_count}")
    report_lines.append(f"WARNING:  {warning_count}")
    report_lines.append(f"ERROR:    {error_count}")
    report_lines.append("")
    
    # Detailed results
    report_lines.append("DETAILED RESULTS")
    report_lines.append("-" * 40)
    report_lines.append("")
    
    for result in results:
        report_lines.append(f"ID:       {result['id']}")
        report_lines.append(f"Title:    {result['title']}")
        report_lines.append(f"Status:   {result['status']}")
        
        if result['ffprobe_duration']:
            report_lines.append(f"Duration: {result['ffprobe_duration']:.1f}s (db: {result['db_duration']}s)")
        else:
            report_lines.append(f"Duration: N/A (db: {result['db_duration']}s)")
        
        report_lines.append(f"Codec:    {result['codec'] or 'N/A'}")
        report_lines.append(f"Resolution: {result['resolution'] or 'N/A'}")
        
        if not result['file_size_match']:
            report_lines.append(f"Size:     MISMATCH (actual: {result.get('actual_size', 0)}, db: {result.get('db_size', 0)})")
        
        if result['errors']:
            for error in result['errors']:
                report_lines.append(f"Error:    {error}")
        
        if result['warnings']:
            for warning in result['warnings']:
                report_lines.append(f"Warning:  {warning}")
        
        report_lines.append("-" * 40)
        report_lines.append("")
    
    # Problem files list
    problem_files = [r for r in results if r['status'] in ['ERROR', 'WARNING']]
    if problem_files:
        report_lines.append("")
        report_lines.append("=" * 80)
        report_lines.append("PROBLEMATIC FILES REQUIRING ATTENTION")
        report_lines.append("=" * 80)
        report_lines.append("")
        for result in problem_files:
            report_lines.append(f"- {result['id']}: {result['title']} [{result['status']}]")
            if result['errors']:
                for error in result['errors']:
                    report_lines.append(f"    Error: {error}")
            if result['warnings']:
                for warning in result['warnings']:
                    report_lines.append(f"    Warning: {warning}")
        report_lines.append("")
        report_lines.append(f"Total problematic files: {len(problem_files)}")
    
    # Write report
    report_content = "\n".join(report_lines)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
    
    print("\n" + "=" * 80)
    print("VERIFICATION COMPLETE")
    print(f"Total: {len(videos)} | OK: {ok_count} | Warning: {warning_count} | Error: {error_count}")
    print(f"Report saved to: {report_path}")
    
    return results

if __name__ == "__main__":
    main()

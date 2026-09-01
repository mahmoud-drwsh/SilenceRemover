#!/usr/bin/env python3
"""Opt-in, self-cleaning production black-box test for server processing."""
from __future__ import annotations
import argparse, os, subprocess, time, uuid
from pathlib import Path
import httpx
from sr_media_manager import MediaManagerClient

def wait_for(client, file_id, file_type, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client._client.get(client._url(f"/api/files?type={file_type}&check_id={file_id}")); response.raise_for_status()
        rows = response.json()
        if rows and rows[0].get("exists"): return rows[0]
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for {file_type}:{file_id}")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-production", action="store_true")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()
    if not args.confirm_production: parser.error("--confirm-production is required; this test creates and removes production media")
    client = MediaManagerClient(); args.work_dir.mkdir(parents=True, exist_ok=True)
    source_id = f"black-box-{uuid.uuid4().hex[:18]}"; title = f"Black-box production verification {source_id[-6:]}"
    cleanup = [(source_id,"video"),(f"{source_id}-no-overlay","video"),(f"{source_id}-subtitles","subtitle"),(source_id,"audio"),(source_id,"original")]
    try:
        candidates = sorted(client.get_original_files(), key=lambda row: int(row.get("file_size") or 0))
        source = next((row for row in candidates if 0 < int(row.get("file_size") or 0) <= 40*1024*1024), None)
        if not source: raise RuntimeError("No bounded production original is available")
        meta = client._client.get(client._url(f"/api/originals/{source['id']}/download")); meta.raise_for_status()
        original = args.work_dir / f"{source_id}.mkv"
        with httpx.stream("GET", meta.json()["url"], timeout=600) as stream:
            stream.raise_for_status(); original.write_bytes(stream.read())
        clip = args.work_dir / f"{source_id}-clip.mkv"
        subprocess.run(["ffmpeg","-v","error","-y","-i",str(original),"-t","25","-map","0","-c","copy",str(clip)],check=True)
        client.upload_original(source_id, clip); wait_for(client,source_id,"original",90)
        review=wait_for(client,source_id,"audio",args.timeout_seconds)
        if "todo" not in review["tags"] or not str(review.get("title") or "").strip(): raise RuntimeError("invalid review checkpoint")
        response=client._client.put(client._url(f"/api/files/{source_id}?type=audio"),json={"title":title,"tags":["ready"]}); response.raise_for_status()
        subtitle=wait_for(client,f"{source_id}-subtitles","subtitle",args.timeout_seconds)
        no_overlay=wait_for(client,f"{source_id}-no-overlay","video",args.timeout_seconds)
        final=wait_for(client,source_id,"video",args.timeout_seconds)
        if final.get("title") != title or no_overlay.get("title") != title: raise RuntimeError("title did not reach both variants")
        if any(row.get("source_id") != source_id for row in (subtitle,no_overlay,final)): raise RuntimeError("derived media is not linked")
        if not isinstance(final.get("duration"),(int,float)) or final["duration"] <= 0: raise RuntimeError("invalid final duration")
        print({"ok":True,"source_id":source_id,"duration":final["duration"]})
    finally:
        for file_id,file_type in cleanup:
            try:
                wait_for(client,file_id,file_type,1); client.update_tags(file_id,["trash"],file_type); client._client.delete(client._url(f"/api/files/{file_id}?type={file_type}")).raise_for_status()
            except (TimeoutError,httpx.HTTPError): pass
        client.close()
if __name__ == "__main__": main()

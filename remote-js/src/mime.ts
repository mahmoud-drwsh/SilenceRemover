/**
 * MIME tables and sniffing - 1:1 port of the AUDIO_MIME/VIDEO_MIME/MIME_TO_EXT
 * sets in remote/app.py, plus a `sniffMimeFromBytes` helper that mirrors the
 * libmagic-based detection the Python service does with `python-magic`.
 */

import { fileTypeFromBuffer, fileTypeFromStream } from "file-type";

export const AUDIO_MIME = new Set<string>([
  "audio/mpeg",
  "audio/mp3",
  "audio/mp4",
  "audio/wav",
  "audio/x-wav",
  "audio/ogg",
  "audio/opus",
  "application/ogg",
  "audio/flac",
  "audio/x-flac",
  "audio/aac",
  "audio/x-m4a",
]);

export const VIDEO_MIME = new Set<string>([
  "video/mp4",
  "video/x-m4v",
  "video/webm",
  "video/ogg",
  "video/quicktime",
  "video/x-msvideo",
  "video/x-matroska",
]);

export const ALLOWED_MIME = new Set<string>([...AUDIO_MIME, ...VIDEO_MIME]);

export const MIME_TO_EXT: Record<string, string> = {
  "audio/mpeg": ".mp3",
  "audio/mp3": ".mp3",
  "audio/mp4": ".m4a",
  "audio/wav": ".wav",
  "audio/x-wav": ".wav",
  "audio/ogg": ".ogg",
  "audio/opus": ".ogg",
  "application/ogg": ".ogg",
  "audio/flac": ".flac",
  "audio/x-flac": ".flac",
  "audio/aac": ".aac",
  "audio/x-m4a": ".m4a",
  "video/mp4": ".mp4",
  "video/x-m4v": ".m4v",
  "video/webm": ".webm",
  "video/ogg": ".ogv",
  "video/quicktime": ".mov",
  "video/x-msvideo": ".avi",
  "video/x-matroska": ".mkv",
};

const EXT_ALIASES: Record<string, string> = {
  // file-type returns "audio/x-m4a" and "audio/mp4" for distinct M4A audio
  // shapes; we normalize to whichever the Python service actually emits.
  "audio/x-m4a": "audio/x-m4a",
  "audio/m4a": "audio/x-m4a",
};

/** Return the file extension (with dot) for a MIME type, falling back to .bin. */
export function getExtensionForMime(mime: string): string {
  return MIME_TO_EXT[mime] ?? ".bin";
}

/**
 * Sniff the MIME type from the first bytes of a file. Returns null if no
 * type matched. We only consider the file-type library's signature-based
 * detection - exactly the shape of the libmagic output the Python service
 * was relying on.
 */
export async function sniffMimeFromBytes(
  bytes: Uint8Array,
): Promise<string | null> {
  const detected = await fileTypeFromBuffer(bytes);
  if (!detected) return null;
  const raw = detected.mime;
  return EXT_ALIASES[raw] ?? raw;
}

/** Sniff MIME from a file path without reading the whole file into memory. */
export async function sniffMimeFromFile(filePath: string): Promise<string | null> {
  const detected = await fileTypeFromStream(Bun.file(filePath).stream());
  if (!detected) return null;
  const raw = detected.mime;
  return EXT_ALIASES[raw] ?? raw;
}

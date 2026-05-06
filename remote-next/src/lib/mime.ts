export const AUDIO_MIME = new Set<string>([
  "audio/mpeg",
  "audio/mp3",
  "audio/mp4",
  "audio/wav",
  "audio/x-wav",
  "audio/ogg",
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

export const ALLOWED_MIME = new Set([...AUDIO_MIME, ...VIDEO_MIME]);

export const MIME_TO_EXT: Record<string, string> = {
  "audio/mpeg": ".mp3",
  "audio/mp3": ".mp3",
  "audio/mp4": ".m4a",
  "audio/wav": ".wav",
  "audio/x-wav": ".wav",
  "audio/ogg": ".ogg",
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

export function getFileExtension(mimeType: string): string {
  return MIME_TO_EXT[mimeType] ?? ".bin";
}

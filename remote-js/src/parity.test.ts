/**
 * Parity tests for the deterministic helpers that mirror remote/app.py.
 *
 * These don't need network access; they pin down the behavior of the
 * range parser, sanitizers, and MIME tables so the JS port stays in sync
 * with the Python service.
 */

import { describe, expect, test } from "bun:test";
import { parseRangeHeader } from "./range.ts";
import { normalizeTitle, sanitizeFileId, sanitizeFilename } from "./sanitize.ts";
import {
  ALLOWED_MIME,
  AUDIO_MIME,
  MIME_TO_EXT,
  VIDEO_MIME,
  getExtensionForMime,
} from "./mime.ts";

describe("parseRangeHeader", () => {
  test("returns null when missing", () => {
    expect(parseRangeHeader(null, 100)).toBeNull();
    expect(parseRangeHeader(undefined, 100)).toBeNull();
    expect(parseRangeHeader("", 100)).toBeNull();
  });

  test("returns null on bad shape", () => {
    expect(parseRangeHeader("items=0-10", 100)).toBeNull();
    expect(parseRangeHeader("bytes=abc", 100)).toBeNull();
    expect(parseRangeHeader("bytes=0", 100)).toBeNull();
  });

  test("parses simple range", () => {
    expect(parseRangeHeader("bytes=0-99", 100)).toEqual({ start: 0, end: 99 });
    expect(parseRangeHeader("bytes=10-20", 100)).toEqual({ start: 10, end: 20 });
  });

  test("clamps end to size-1", () => {
    expect(parseRangeHeader("bytes=10-200", 100)).toEqual({ start: 10, end: 99 });
  });

  test("handles open end", () => {
    expect(parseRangeHeader("bytes=10-", 100)).toEqual({ start: 10, end: 99 });
  });

  test("handles suffix range", () => {
    expect(parseRangeHeader("bytes=-30", 100)).toEqual({ start: 70, end: 99 });
  });

  test("rejects suffix range zero", () => {
    expect(parseRangeHeader("bytes=-0", 100)).toBeNull();
  });

  test("rejects start >= size", () => {
    expect(parseRangeHeader("bytes=100-", 100)).toBeNull();
  });

  test("rejects end < start", () => {
    expect(parseRangeHeader("bytes=20-10", 100)).toBeNull();
  });

  test("uses only the first range", () => {
    expect(parseRangeHeader("bytes=0-9,20-29", 100)).toEqual({ start: 0, end: 9 });
  });

  test("suffix larger than size clamps to 0", () => {
    expect(parseRangeHeader("bytes=-200", 100)).toEqual({ start: 0, end: 99 });
  });
});

describe("sanitizeFilename", () => {
  test("returns empty on null/undefined", () => {
    expect(sanitizeFilename(null)).toBe("");
    expect(sanitizeFilename(undefined)).toBe("");
    expect(sanitizeFilename("")).toBe("");
  });

  test("removes reserved filesystem chars", () => {
    expect(sanitizeFilename("a/b\\c:d*e?f\"g<h>i|j")).toBe("abcdefghij");
  });

  test("removes control chars", () => {
    expect(sanitizeFilename("a\nb\rc\td\u0000e")).toBe("abcde");
  });

  test("collapses whitespace and trims", () => {
    expect(sanitizeFilename("  a   b  c  ")).toBe("a b c");
  });

  test("caps at 200 characters", () => {
    const big = "x".repeat(500);
    expect(sanitizeFilename(big)).toHaveLength(200);
  });
});

describe("sanitizeFileId", () => {
  test("returns empty on null/undefined", () => {
    expect(sanitizeFileId(null)).toBe("");
    expect(sanitizeFileId(undefined)).toBe("");
    expect(sanitizeFileId("")).toBe("");
  });

  test("removes path traversal", () => {
    expect(sanitizeFileId("../../etc/passwd")).toBe("etcpasswd");
    expect(sanitizeFileId("..\\foo")).toBe("foo");
  });

  test("removes dangerous chars", () => {
    expect(sanitizeFileId('a:b*c?d"e<f>g|h')).toBe("abcdefgh");
  });

  test("preserves dots, hyphens, underscores", () => {
    expect(sanitizeFileId("my-video_001.test")).toBe("my-video_001.test");
  });

  test("caps at 200 characters", () => {
    const big = "x".repeat(500);
    expect(sanitizeFileId(big)).toHaveLength(200);
  });
});

describe("normalizeTitle", () => {
  test("trims whitespace", () => {
    expect(normalizeTitle("  hello  ")).toBe("hello");
  });

  test("returns empty on null/undefined", () => {
    expect(normalizeTitle(null)).toBe("");
    expect(normalizeTitle(undefined)).toBe("");
  });
});

describe("MIME tables", () => {
  test("ALLOWED_MIME is the union of audio + video", () => {
    expect(ALLOWED_MIME.size).toBe(AUDIO_MIME.size + VIDEO_MIME.size);
  });

  test("getExtensionForMime falls back to .bin", () => {
    expect(getExtensionForMime("application/octet-stream")).toBe(".bin");
  });

  test("known mappings match Python MIME_TO_EXT", () => {
    expect(MIME_TO_EXT["audio/mpeg"]).toBe(".mp3");
    expect(MIME_TO_EXT["audio/ogg"]).toBe(".ogg");
    expect(MIME_TO_EXT["video/mp4"]).toBe(".mp4");
    expect(MIME_TO_EXT["video/quicktime"]).toBe(".mov");
    expect(MIME_TO_EXT["video/x-matroska"]).toBe(".mkv");
  });
});

/**
 * Parity tests for the deterministic helpers that mirror remote/app.py.
 *
 * These don't need network access; they pin down the behavior of the
 * range parser, sanitizers, and MIME tables so the JS port stays in sync
 * with the Python service.
 */

import { describe, expect, test } from "bun:test";
import { parseRangeHeader } from "./range.ts";
import { addTagListConditions, parseContentLengthHeader } from "./routes/files.ts";
import { normalizeTitle, sanitizeFileId, sanitizeFilename } from "./sanitize.ts";
import { HttpError } from "./schemas.ts";
import {
  ALLOWED_MIME,
  AUDIO_MIME,
  MIME_TO_EXT,
  VIDEO_MIME,
  getExtensionForMime,
  normalizeDetectedMime,
  sniffMimeFromBytes,
  sniffMimeFromFile,
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

describe("parseContentLengthHeader", () => {
  test("parses decimal byte counts", () => {
    expect(parseContentLengthHeader("0")).toBe(0);
    expect(parseContentLengthHeader("1048576")).toBe(1048576);
    expect(parseContentLengthHeader(" 42 ")).toBe(42);
  });

  test("requires the header", () => {
    expect(() => parseContentLengthHeader(undefined)).toThrow(HttpError);
    try {
      parseContentLengthHeader(undefined);
    } catch (err) {
      expect(err).toBeInstanceOf(HttpError);
      expect((err as HttpError).status).toBe(411);
    }
  });

  test("rejects invalid byte counts", () => {
    for (const value of ["", "-1", "1.5", "abc", "10 bytes"]) {
      try {
        parseContentLengthHeader(value);
        throw new Error(`Expected ${value} to fail`);
      } catch (err) {
        expect(err).toBeInstanceOf(HttpError);
        expect((err as HttpError).status).toBe(400);
      }
    }
  });
});

describe("addTagListConditions", () => {
  test("uses jsonb containment for explicit trash filter", () => {
    const conditions = ["project = $1", "type = $2"];
    const params: (string | number | boolean | null)[] = ["temp", "video"];

    addTagListConditions({
      conditions,
      params,
      tagList: ["trash"],
      includeTrash: false,
      includePending: false,
    });

    expect(conditions).toContain(
      "CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END @> $3::jsonb",
    );
    expect(params[2]).toBe('["trash"]');
  });

  test("excludes trash and pending with normalized jsonb containment by default", () => {
    const conditions = ["project = $1"];
    const params: (string | number | boolean | null)[] = ["temp"];

    addTagListConditions({
      conditions,
      params,
      tagList: null,
      includeTrash: false,
      includePending: false,
    });

    expect(conditions).toContain(
      "NOT (CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END @> $2::jsonb)",
    );
    expect(conditions).toContain(
      "NOT (CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END @> $3::jsonb)",
    );
    expect(params.slice(1)).toEqual(['["trash"]', '["pending"]']);
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
    expect(MIME_TO_EXT["audio/opus"]).toBe(".ogg");
    expect(MIME_TO_EXT["application/ogg"]).toBe(".ogg");
    expect(MIME_TO_EXT["video/mp4"]).toBe(".mp4");
    expect(MIME_TO_EXT["video/quicktime"]).toBe(".mov");
    expect(MIME_TO_EXT["video/x-matroska"]).toBe(".mkv");
  });

  test("accepts Ogg audio snippets detected as application/ogg", async () => {
    const bytes = new Uint8Array(
      await Bun.file(new URL("../../tests/fixtures/test_audio.ogg", import.meta.url)).arrayBuffer(),
    );
    const mime = await sniffMimeFromBytes(bytes);
    expect(mime).toBe("application/ogg");
    expect(ALLOWED_MIME.has(mime!)).toBe(true);
    expect(getExtensionForMime(mime!)).toBe(".ogg");
  });

  test("sniffs MIME from file without using incompatible web stream detector", async () => {
    const mime = await sniffMimeFromFile(
      new URL("../../tests/fixtures/test_audio.ogg", import.meta.url).pathname,
    );
    expect(mime).toBe("application/ogg");
  });

  test("accepts Ogg audio snippets detected with codec parameters", () => {
    const mime = normalizeDetectedMime("audio/ogg; codecs=opus");
    expect(mime).toBe("audio/ogg");
    expect(ALLOWED_MIME.has(mime)).toBe(true);
    expect(getExtensionForMime(mime)).toBe(".ogg");
  });
});

describe("static Media Manager UI", () => {
  test("pending video options include Move to Trash", async () => {
    const html = await Bun.file(new URL("../static/index.html", import.meta.url)).text();
    expect(html).toContain("currentFilter === 'all' || currentFilter === 'pending'");
    expect(html).toContain("confirmMoveToTrash('${safeId}')");
  });

  test("video folder actions use card tags instead of refetching all videos", async () => {
    const html = await Bun.file(new URL("../static/index.html", import.meta.url)).text();

    expect(html).toContain('class="file-card video-card"');
    expect(html).toContain('data-tags="${tagsJson}"');
    expect(html).toContain("function getVideoCardTags(fileId)");
    expect(html).toContain("const currentTags = getVideoCardTags(fileId);");

    const removeTagBody = html.slice(
      html.indexOf("async function removeTagFromFile"),
      html.indexOf("function confirmMoveToReady"),
    );
    const openFolderBody = html.slice(
      html.indexOf("function openFolderModal"),
      html.indexOf("function closeFolderModal"),
    );

    expect(removeTagBody).toContain("async function removeTagFromFile");
    expect(openFolderBody).toContain("function openFolderModal");
    expect(removeTagBody).not.toContain("fetch(`${API_BASE}/files?type=${TYPE_VIDEO}`)");
    expect(openFolderBody).not.toContain("fetch(`${API_BASE}/files?type=${TYPE_VIDEO}`)");
  });
});

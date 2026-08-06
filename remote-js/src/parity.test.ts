/**
 * Parity tests for the deterministic helpers that mirror remote/app.py.
 *
 * These don't need network access; they pin down the behavior of the
 * range parser, sanitizers, and MIME tables so the JS port stays in sync
 * with the Python service.
 */

import { describe, expect, test } from "bun:test";
import { parseRangeHeader } from "./range.ts";
import {
  addTagListConditions,
  mapUploadMetadataInsertError,
  parseContentLengthHeader,
} from "./routes/files.ts";
import { normalizeTitle, sanitizeFileId, sanitizeFilename } from "./sanitize.ts";
import { AUDIO_TAGS, HttpError } from "./schemas.ts";
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

describe("mapUploadMetadataInsertError", () => {
  test("turns a concurrent duplicate metadata insert into a conflict", () => {
    const error = mapUploadMetadataInsertError({ code: "23505" }, "upload-42");

    expect(error).toBeInstanceOf(HttpError);
    expect((error as HttpError).status).toBe(409);
    expect((error as Error).message).toBe("File with id 'upload-42' already exists");
  });

  test("preserves non-unique database errors", () => {
    const databaseError = { code: "42P01", message: "missing relation" };

    expect(mapUploadMetadataInsertError(databaseError, "upload-42")).toBe(databaseError);
  });
});

describe("addTagListConditions", () => {
  test("uses jsonb containment for explicit trash filter", () => {
    const conditions = ["project = $1", "type = $2"];
    const params: (string | number | boolean | null | string[])[] = ["temp", "video"];

    addTagListConditions({
      conditions,
      params,
      tagList: ["trash"],
      includeTrash: false,
      includePending: false,
    });

    expect(conditions).toContain(
      "CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END @> CAST($3 AS jsonb)",
    );
    expect(params[2]).toEqual(["trash"]);
  });

  test("excludes only trash by default", () => {
    const conditions = ["project = $1"];
    const params: (string | number | boolean | null | string[])[] = ["temp"];

    addTagListConditions({
      conditions,
      params,
      tagList: null,
      includeTrash: false,
      includePending: false,
    });

    expect(conditions).toContain(
      "NOT (CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END @> CAST($2 AS jsonb))",
    );
    expect(conditions).not.toContain(
      "NOT (CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END @> CAST($3 AS jsonb))",
    );
    expect(params.slice(1)).toEqual([["trash"]]);
  });

  test("can keep a dedicated video folder out of the virtual all view", () => {
    const conditions = ["project = $1", "type = $2"];
    const params: (string | number | boolean | null | string[])[] = ["temp", "video"];

    addTagListConditions({
      conditions,
      params,
      tagList: null,
      includeTrash: false,
      includePending: false,
      excludedTags: ["no-overlay"],
    });

    expect(params.slice(2)).toEqual([["trash"], ["no-overlay"]]);
    expect(conditions.at(-1)).toContain("NOT (");
  });
});

describe("AUDIO_TAGS", () => {
  test("all is a virtual view and not a persisted audio tag", () => {
    expect(AUDIO_TAGS.has("all")).toBe(false);
    expect(AUDIO_TAGS.has("trash")).toBe(true);
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

  test("normalizes the Matroska MIME reported by file-type", () => {
    expect(normalizeDetectedMime("video/matroska")).toBe("video/x-matroska");
  });
});

describe("frontend Media Manager UI", () => {
  test("pending video options include Move to Trash", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();
    expect(html).toContain("currentFilter === 'all' || currentFilter === 'pending'");
    expect(html).toContain("confirmMoveToTrash('${safeId}')");
  });

  test("video folder actions use card tags instead of refetching all videos", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();

    expect(html).toContain('class="file-card video-card variant-card"');
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
    expect(removeTagBody).not.toContain("newTags.push('all')");
    expect(removeTagBody).not.toContain("fetch(`${API_BASE}/files?type=${TYPE_VIDEO}`)");
    expect(openFolderBody).not.toContain("fetch(`${API_BASE}/files?type=${TYPE_VIDEO}`)");
  });

  test("video restore and folder save do not write an all tag", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();

    expect(html).toContain("const restoreTags = type === TYPE_AUDIO ? ['todo'] : []");
    expect(html).toContain("const newTags = selectedFolders;");
    expect(html).not.toContain("const newTags = ['all', ...selectedFolders]");
  });

  test("linked derived cards offer original downloads without an Originals view", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();
    const routes = await Bun.file(new URL("./routes/projectSpa.ts", import.meta.url)).text();

    expect(html).toContain("function downloadOriginal(sourceId)");
    expect(html).toContain("<strong>Original</strong>");
    expect(html).toContain("file.source_id ? escapeJs(file.source_id)");
    expect(html).not.toContain('href="./originals"');
    expect(routes).not.toContain("/originals");
  });

  test("normal video cards present linked no-overlay and designer variants", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();
    const filesRoute = await Bun.file(new URL("./routes/files.ts", import.meta.url)).text();

    expect(html).toContain("'no-overlay': '🎬 No Overlay'");
    expect(html).toContain("file.no_overlay_id ? escapeJs(file.no_overlay_id)");
    expect(html).toContain("<strong>Silence Removed</strong>");
    expect(html).toContain("file.designer_video_id ? escapeJs(file.designer_video_id)");
    expect(html).toContain("function openDesignerUpload(targetId, targetTitle)");
    expect(filesRoute).toContain('tag === "no-overlay" || tag === "designer" || tag === "trash"');
    expect(filesRoute).toContain("candidate.source_id = source.source_id");
    expect(filesRoute).toContain("AS no_overlay_id");
    expect(filesRoute).toContain("AS designer_video_id");
  });

  test("video card context menu exists for every filter before the footer is rendered", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();
    const cardRenderer = html.slice(html.indexOf("function renderFileCard(file)"), html.indexOf("function openDesignerUpload"));

    expect(cardRenderer.indexOf("let menuItem = '';"))
      .toBeLessThan(cardRenderer.indexOf("if (currentFilter === 'trash')"));
  });

  test("audio is a title-review queue, not a general media-management surface", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();
    const audioRenderer = html.slice(html.indexOf("function renderAudioCard(file"), html.indexOf("async function deleteFile"));

    expect(html).toContain("const AUDIO_TABS = ['todo', 'ready'];");
    expect(audioRenderer).toContain("Approve title");
    expect(audioRenderer).toContain("Reopen review");
    expect(audioRenderer).not.toContain("downloadOriginal");
    expect(audioRenderer).not.toContain("confirmMoveToTrash");
    expect(audioRenderer).not.toContain("btn-menu");
  });

  test("non-admin review is always oldest first and has no sort control", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();

    expect(html).toContain("function updateSortControl()");
    expect(html).toContain("currentSort = 'asc';");
    expect(html).toContain("button.style.display = 'none';");
    expect(html).toContain("if (!isAdminMode()) return;");
  });

  test("only admins can trash videos while title reviewers can discard unusable audio", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();
    const videoRenderer = html.slice(html.indexOf("function renderFileCard(file)"), html.indexOf("function openDesignerUpload"));
    const audioRenderer = html.slice(html.indexOf("function renderAudioCard(file"), html.indexOf("async function deleteFile"));

    expect(videoRenderer).toContain("const canManageVideoTrash = isAdminMode();");
    expect(videoRenderer).toContain("canManageVideoTrash ?");
    expect(audioRenderer).toContain("Discard audio");
    expect(html).toContain("function discardAudio(fileId)");
    expect(html).toContain("if (type === TYPE_VIDEO && !isAdminMode()) return;");
  });

  test("designer queue filters pipeline finals with no designer upload", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();
    const filesRoute = await Bun.file(new URL("./routes/files.ts", import.meta.url)).text();

    expect(html).toContain("'needs-designer': '✨ Needs Designer'");
    expect(html).toContain("&designer_missing=true");
    expect(filesRoute).toContain('designer_missing requires type=video');
    expect(filesRoute).toContain('designer_candidate.designer_of_id');
  });
});

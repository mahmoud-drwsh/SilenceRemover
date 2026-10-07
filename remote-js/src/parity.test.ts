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
  excludedVideoVariantTags,
  activeDesignerRevisionSql,
  canonicalVideoTitleSql,
  cardStateSql,
  cardTrashConditionSql,
  designerLinkSql,
  legacyOverlaidJoinSql,
  writeThroughLegacyOverlaid,
  REMOVED_VIDEO_VIEWS,
  VIDEO_VIEWS,
  mapUploadMetadataInsertError,
  parseContentLengthHeader,
} from "./routes/files.ts";
import { normalizeTitle, sanitizeFileId, sanitizeFilename } from "./sanitize.ts";
import { cardTitleNeedsLegacy, cardTitleNeedsLegacySql, legacyOverlaidMatchSql } from "./videoSql.ts";
import { AUDIO_TAGS, VIDEO_TAGS, HttpError, validateVideoTags } from "./schemas.ts";
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

describe("excludedVideoVariantTags", () => {
  test("legacy no-overlay rows stay listable as canonical cards", () => {
    expect(excludedVideoVariantTags(null)).toEqual(["designer"]);
    expect(excludedVideoVariantTags(null, true)).toEqual(["designer"]);
  });
});

describe("video virtual views", () => {
  test("removed view names fall back to All", () => {
    expect([...VIDEO_VIEWS]).toEqual(["all", "needs-designer", "designer", "pending", "trash"]);
    expect([...REMOVED_VIDEO_VIEWS]).toEqual(["pipeline-final", "no-overlay"]);
  });
});

describe("legacy designer-link fallback (#44)", () => {
  test("designer links match the card and each legacy overlaid row, by ID probes", () => {
    const link = designerLinkSql("s", "source", "candidate");
    expect(link).toContain("candidate.designer_of_id = source.id");
    expect(link).toContain("legacy_link.id = candidate.designer_of_id");
    expect(link).toContain("legacy_link.id = left(candidate.id, -length('-designer'))");
    expect(link).toContain("legacy_link.source_id = source.source_id");
  });

  test("one lateral finds the primary legacy overlaid row", () => {
    const join = legacyOverlaidJoinSql("s", "source");
    expect(join).toMatch(/^LEFT JOIN LATERAL \(/);
    expect(join).toContain("FROM s.files AS legacy_row");
    expect(join).toContain("legacy_row.id = left(source.id, -length('-no-overlay'))");
    expect(join).toContain("LIMIT 1");
    expect(join).toMatch(/\) AS legacy ON TRUE$/);
    // No column of the lateral has the name project, type or tags, so the
    // unqualified columns of addTagListConditions stay unambiguous.
    const columns = join.slice(join.indexOf("SELECT"), join.indexOf("FROM s.files"));
    expect(columns).not.toMatch(/AS (project|type|tags)\b|legacy_row\.\*/);
  });

  test("the card pointer wins over the legacy overlaid pointer", () => {
    expect(activeDesignerRevisionSql("source", "legacy"))
      .toBe("COALESCE(source.active_designer_revision_id, legacy.active_designer_revision_id)");
  });

  test("the card title wins unless it is blank or has the old suffix", () => {
    const title = canonicalVideoTitleSql("source", "legacy");
    expect(title).toContain(cardTitleNeedsLegacySql("source"));
    expect(title).toContain("COALESCE(BTRIM(legacy.title), '') <> ''");
    expect(title).toMatch(/ELSE source\.title END\)$/);
    expect(cardTitleNeedsLegacy(null)).toBe(true);
    expect(cardTitleNeedsLegacy("  ")).toBe(true);
    expect(cardTitleNeedsLegacy("Approved (No Overlay)")).toBe(true);
    expect(cardTitleNeedsLegacy("Renamed")).toBe(false);
  });

  test("the legacy overlaid row holds the card state while it exists", () => {
    expect(cardStateSql("legacy", "visibility", "X"))
      .toBe("(CASE WHEN legacy.id IS NOT NULL THEN legacy.visibility ELSE X END)");
    const conditions = ["project = $1"];
    const params: (string | number | boolean | null | string[])[] = ["temp"];
    addTagListConditions({
      conditions, params, tagList: null, includeTrash: false, includePending: false,
      trashCondition: cardTrashConditionSql("legacy"),
    });
    expect(conditions.at(-1)).toBe(
      "NOT ((CASE WHEN legacy.id IS NOT NULL THEN legacy.visibility = 'trash' ELSE CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END @> CAST($2 AS jsonb) END))",
    );
  });

  test("list, count, views, publish, PUT, DELETE, stream and designer target use the lateral", async () => {
    const filesRoute = await Bun.file(new URL("./routes/files.ts", import.meta.url)).text();
    const stream = await Bun.file(new URL("./routes/stream.ts", import.meta.url)).text();
    const uploads = await Bun.file(new URL("./routes/uploads.ts", import.meta.url)).text();
    expect(filesRoute).toContain("FROM ${ident}.files AS source ${legacyJoin} WHERE ${whereClause}");
    expect(filesRoute).toContain("FROM ${ident}.files AS source\n     ${legacyJoin}");
    expect(filesRoute).toContain("if (view === \"trash\") conditions.push(`${visibilityExpr} = 'trash'`)");
    expect(filesRoute).toContain("if (view === \"pending\") conditions.push(`${publicationExpr} = 'pending'`)");
    expect(filesRoute).toContain("trashCondition: cardTrashConditionSql(\"legacy\")");
    expect(filesRoute).toContain("writeThroughLegacyOverlaid(tx, ident, project, id, { publicationStatus: \"published\" })");
    expect(filesRoute).toContain("trash: tags.includes(\"trash\")");
    expect(filesRoute).toContain("legacyOverlaidJoinSql(ident, \"file\")");
    expect(stream).toContain("legacyOverlaidJoinSql(ident, \"file\", \"file_legacy\")");
    expect(uploads).toContain("cardStateSql(\"legacy\", \"visibility\", visibilitySql(\"designer_target\"))");
  });

  test("write-through changes the legacy overlaid rows in the same transaction", async () => {
    const statements: { query: string; params: unknown[] }[] = [];
    const tx = { unsafe: async (query: string, params: unknown[]) => { statements.push({ query, params }); return [{ id: "s" }]; } };
    const changed = await writeThroughLegacyOverlaid(tx as never, "s", "p", "s-no-overlay", { trash: true, publicationStatus: "published", title: "New" });
    expect(changed).toBe(1);
    const { query, params } = statements[0]!;
    expect(query).toContain("UPDATE s.files AS legacy");
    expect(query).toContain("- 'trash') || CASE WHEN $3::boolean THEN '[\"trash\"]'::jsonb ELSE '[]'::jsonb END");
    expect(query).toContain("visibility = CASE WHEN $3::boolean THEN 'trash' ELSE 'active' END");
    expect(query).toContain("publication_status = $4");
    expect(query).toContain("title = $5");
    expect(query).toContain(legacyOverlaidMatchSql("card", "legacy"));
    expect(params).toEqual(["s-no-overlay", "p", true, "published", "New"]);
    expect(await writeThroughLegacyOverlaid(tx as never, "s", "p", "s-no-overlay", {})).toBe(0);
    expect(statements.length).toBe(1);
  });

  test("the fallback lives in one marked block", async () => {
    const filesRoute = await Bun.file(new URL("./routes/files.ts", import.meta.url)).text();
    expect(filesRoute.split("Legacy designer-link fallback (#44): remove after the data move.").length).toBe(2);
  });
});

describe("AUDIO_TAGS", () => {
  test("all is a virtual view and not a persisted audio tag", () => {
    expect(AUDIO_TAGS.has("all")).toBe(false);
    expect(AUDIO_TAGS.has("trash")).toBe(true);
  });
});

describe("VIDEO_TAGS", () => {
  test("only trash remains writable", () => {
    expect([...VIDEO_TAGS]).toEqual(["trash"]);
    expect(validateVideoTags([])).toEqual([]);
    expect(validateVideoTags(["trash"])).toEqual(["trash"]);
    for (const legacy of ["all", "designer", "no-overlay", "pending", "FB", "TT", "YT"]) {
      expect(() => validateVideoTags([legacy])).toThrow(HttpError);
    }
  });
});

describe("explicit video lifecycle", () => {
  test("designer uploads and video downloads use the canonical approved title", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();
    const uploads = await Bun.file(new URL("./routes/uploads.ts", import.meta.url)).text();
    const stream = await Bun.file(new URL("./routes/stream.ts", import.meta.url)).text();

    expect(html).toContain("document.getElementById('designer-title').value = targetTitle");
    expect(html).not.toContain("${targetTitle} (Designer)");
    expect(uploads).toContain("title: target.title");
    expect(uploads).toContain("canonicalVideoTitleSql(\"designer_target\", \"legacy\")");
    expect(uploads).toContain('target.media_variant !== "no-overlay"');
    expect(stream).toContain("canonical_download_title");
  });

  test("admin design-system assets receive usable MIME types", async () => {
    const admin = await Bun.file(new URL("./routes/admin.ts", import.meta.url)).text();
    expect(admin).toContain('"text/css; charset=utf-8"');
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
  test("ALLOWED_MIME does not include the removed subtitle MIME", () => {
    expect(ALLOWED_MIME.has("application/x-subrip")).toBe(false);
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
  test("video cards offer admin-only trash without folder placement", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();
    expect(html).not.toContain("Add to Folder");
    expect(html).toContain("confirmMoveToTrash('${safeId}')");
  });

  test("video navigation uses virtual views rather than folders or publisher tags", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();

    expect(html).toContain('class="file-card video-card variant-card"');
    expect(html).toContain("const VIDEO_TABS = ['all', 'needs-designer', 'designer', 'pending', 'trash'];");
    expect(html).toContain("const REMOVED_VIDEO_TABS = ['pipeline-final', 'no-overlay'];");
    expect(html).toContain("if (section === 'video' && REMOVED_VIDEO_TABS.includes(filter)) filter = 'all';");
    expect(html).not.toContain("Pipeline Final");
    expect(html).not.toContain("'no-overlay': '🎬 No Overlay'");
    expect(html).toContain("&view=${encodeURIComponent(currentFilter)}");
    expect(html).not.toContain("'FB'");
    expect(html).not.toContain("'TT'");
  });

  test("focused views reclaim the desktop navigation column when navigation is hidden", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();
    const css = await Bun.file(new URL("../frontend/design-system.css", import.meta.url)).text();

    expect(html).toContain("mm-navigation-hidden");
    expect(css).toContain("body.mm-app.mm-navigation-hidden");
    expect(css).toContain("body.mm-app.mm-navigation-hidden > main");
  });

  test("media lists page immediately and prefetch later cards instead of loading every card", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();
    const filesRoute = await Bun.file(new URL("./routes/files.ts", import.meta.url)).text();

    expect(filesRoute).toContain("const limitParam = url.searchParams.get(\"limit\")");
    expect(filesRoute).toContain('"X-Has-More"');
    expect(html).toContain("const PAGE_SIZE = 24;");
    expect(html).toContain("&limit=${PAGE_SIZE}&offset=${offset}");
    expect(html).toContain("function schedulePagePrefetch");
    expect(html).toContain("function loadMoreFiles");
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

  test("the no-overlay video is the canonical card with linked designer variants", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();
    const filesRoute = await Bun.file(new URL("./routes/files.ts", import.meta.url)).text();

    expect(html).not.toContain("file.no_overlay_id");
    expect(html).toContain("const canUploadDesigner = file.media_variant === 'no-overlay';");
    expect(html).toContain("href=\"${videoStreamUrl}\" download>✂️ <span><strong>Silence Removed</strong>");
    expect(html).toContain("file.designer_video_id ? escapeJs(file.designer_video_id)");
    expect(html).not.toContain("subtitle_id");
    expect(html).not.toContain("<strong>Subtitles</strong>");
    expect(html).not.toContain("type=subtitle");
    expect(html).toContain("function openDesignerUpload(targetId, targetTitle)");
    expect(filesRoute).toContain("excludedVideoVariantTags(tagList, designerMissing)");
    expect(filesRoute).toContain("source.designer_of_id IS NULL");
    expect(filesRoute).toContain("conditions.push(`${videoVariantSql(\"source\")} = 'no-overlay'`);");
    expect(filesRoute).not.toContain("no_overlay_id");
    expect(filesRoute).toContain("AS designer_video_id");
    expect(filesRoute).not.toContain("subtitle_id");
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

    expect(html).toContain("const AUDIO_TABS = ['todo', 'approved', 'trash'];");
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

  test("designer queue filters no-overlay cards with no designer upload", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();
    const filesRoute = await Bun.file(new URL("./routes/files.ts", import.meta.url)).text();

    expect(html).toContain("'needs-designer': '✨ Needs Designer'");
    expect(html).toContain("&view=${encodeURIComponent(currentFilter)}");
    expect(filesRoute).toContain("view === \"needs-designer\"");
    expect(filesRoute).toContain('AND candidate.type=\'video\' AND ${designerLinkSql(ident, "source", "candidate")}');
  });

  test("an explicit All URL is not replaced by the designer queue", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();

    expect(html).toContain("section === 'video' && !isAdminMode() && !filter");
  });

  test("designer uploads use same-origin multipart URLs", async () => {
    const uploadsRoute = await Bun.file(new URL("./routes/uploads.ts", import.meta.url)).text();

    expect(uploadsRoute).toContain("session.designer_of_id && token");
    expect(uploadsRoute).toContain('/parts/:partNumber');
    expect(uploadsRoute).toContain("uploadMultipartPart(");
  });

  test("designer queue hides redundant folder navigation", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();

    expect(html).toContain("if (currentSection === 'video' && !isAdmin)");
    expect(html).toContain("The designer enters through one focused queue");
  });

  test("bulk audio approval is admin-only, confirmed, and excludes trash", async () => {
    const html = await Bun.file(new URL("../frontend/index.html", import.meta.url)).text();
    const filesRoute = await Bun.file(new URL("./routes/files.ts", import.meta.url)).text();

    expect(html).toContain('id="approve-pending-audio"');
    expect(html).toContain("function confirmApprovePendingAudio()");
    expect(html).toContain("Approve all pending audio?");
    expect(html).toContain("body: JSON.stringify({ confirm: true })");
    expect(filesRoute).toContain('"/projects/:token/:project/api/audio/approve-pending"');
    expect(filesRoute).toContain("Explicit confirmation is required");
    expect(filesRoute).toContain("approved_count: rows.length");
  });
});

describe("removed overlay, logo, subtitle and remux features (#44)", () => {
  const read = (path: string) => Bun.file(new URL(path, import.meta.url)).text();

  test("no route serves the remux queue or an overlay logo", async () => {
    const index = await read("./index.ts");
    const admin = await read("./routes/admin.ts");
    const files = await read("./routes/files.ts");
    const processing = await read("./routes/sourceProcessing.ts");
    const adminHtml = await read("../frontend/admin.html");

    expect(index).not.toContain("remux");
    expect(await Bun.file(new URL("./routes/remux.ts", import.meta.url)).exists()).toBe(false);
    for (const source of [admin, files, processing, adminHtml]) {
      expect(source).not.toContain("overlay-logo");
      expect(source).not.toContain("project_overlay_logos");
    }
    expect(admin).not.toContain("overlay_logo_configured");
  });

  test("uploads reject the subtitle type and the pipeline-final variant", async () => {
    const uploads = await read("./routes/uploads.ts");

    expect(uploads).toContain('if (type !== "audio" && type !== "video" && type !== "original") throw new HttpError(400, "Invalid type");');
    expect(uploads).toContain('!["no-overlay", "designer"].includes(mediaVariant)');
    expect(uploads).not.toContain("SUBTITLE_MIME");
  });

  test("the worker API accepts only review audio and the no-overlay video", async () => {
    const processing = await read("./routes/sourceProcessing.ts");

    expect(processing).toContain('kind === "review_audio"');
    expect(processing).toContain('kind === "no_overlay_video"');
    expect(processing).not.toContain('"overlaid_video"');
    expect(processing).not.toContain("subtitle_uploaded");
    expect(processing).not.toContain("overlaid_uploaded");
    expect(processing).not.toContain("srt_text=");
  });

  test("startup does not create or re-assert the removed schema", async () => {
    const db = await read("./db.ts");

    expect(db).not.toContain("CREATE TABLE IF NOT EXISTS ${ident}.subtitle_remux_jobs");
    expect(db).not.toContain("CREATE TABLE IF NOT EXISTS ${ident}.project_overlay_logos");
    expect(db).not.toContain("srt_text text");
    expect(db).not.toContain("ADD CONSTRAINT files_type_check");
    expect(db).not.toContain("ADD CONSTRAINT upload_sessions_type_check");
    expect(db).not.toContain("DROP TABLE");
    expect(db).not.toContain("DROP COLUMN");
    expect(db).not.toContain("'original', 'subtitle'");
  });

  test("storage totals do not count the subtitle prefix", async () => {
    const storage = await read("./storage.ts");

    expect(storage).toContain('for (const fileType of ["audio", "video", "original"] as const)');
  });
});

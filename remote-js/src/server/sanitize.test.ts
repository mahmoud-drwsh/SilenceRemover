// Run: node --test src/server/sanitize.test.ts
// The file-name and file-id sanitizers. Cases from the old parity.test.ts
// (commit 2f1eb5b).
import assert from "node:assert/strict";
import { test } from "node:test";
import { normalizeTitle, sanitizeFileId, sanitizeFilename } from "./sanitize.ts";

test("sanitizeFilename: null, undefined and empty give an empty string", () => {
  assert.equal(sanitizeFilename(null), "");
  assert.equal(sanitizeFilename(undefined), "");
  assert.equal(sanitizeFilename(""), "");
});

test("sanitizeFilename: removes the reserved file-system characters", () => {
  assert.equal(sanitizeFilename('a/b\\c:d*e?f"g<h>i|j'), "abcdefghij");
});

test("sanitizeFilename: removes path traversal separators", () => {
  assert.equal(sanitizeFilename("../../etc/passwd"), "....etcpasswd");
  assert.equal(sanitizeFilename("..\\..\\boot.ini"), "....boot.ini");
});

test("sanitizeFilename: removes control characters", () => {
  assert.equal(sanitizeFilename("a\nb\rc\td\u0000e"), "abcde");
});

test("sanitizeFilename: collapses white space and trims", () => {
  assert.equal(sanitizeFilename("  a   b  c  "), "a b c");
});

test("sanitizeFilename: keeps Arabic text", () => {
  assert.equal(sanitizeFilename("عنوان  الدرس"), "عنوان الدرس");
});

test("sanitizeFilename: caps at 200 characters", () => {
  assert.equal(sanitizeFilename("x".repeat(500)).length, 200);
});

test("sanitizeFileId: null, undefined and empty give an empty string", () => {
  assert.equal(sanitizeFileId(null), "");
  assert.equal(sanitizeFileId(undefined), "");
  assert.equal(sanitizeFileId(""), "");
});

test("sanitizeFileId: removes path traversal", () => {
  assert.equal(sanitizeFileId("../../etc/passwd"), "etcpasswd");
  assert.equal(sanitizeFileId("..\\foo"), "foo");
  assert.equal(sanitizeFileId("a\u0000b"), "ab");
  assert.equal(sanitizeFileId("/abs/path"), "abspath");
});

test("sanitizeFileId: removes the dangerous characters", () => {
  assert.equal(sanitizeFileId('a:b*c?d"e<f>g|h'), "abcdefgh");
});

test("sanitizeFileId: keeps dots, hyphens and underscores", () => {
  assert.equal(sanitizeFileId("my-video_001.test"), "my-video_001.test");
});

test("sanitizeFileId: caps at 200 characters", () => {
  assert.equal(sanitizeFileId("x".repeat(500)).length, 200);
});

test("normalizeTitle: trims, and null or undefined give an empty string", () => {
  assert.equal(normalizeTitle("  hello  "), "hello");
  assert.equal(normalizeTitle(null), "");
  assert.equal(normalizeTitle(undefined), "");
});

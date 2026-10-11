// Run: node --test src/server/mime.test.ts
// The MIME tables and the MIME sniffing. Cases from the old parity.test.ts
// (commit 2f1eb5b).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import {
  ALLOWED_MIME, AUDIO_MIME, getExtensionForMime, MIME_TO_EXT, normalizeDetectedMime, sniffMimeFromBytes,
  sniffMimeFromFile, VIDEO_MIME,
} from "./mime.ts";

// The Ogg/Opus fixture of the repository (tests/fixtures at the repository root).
const OGG_FIXTURE = fileURLToPath(new URL("../../../tests/fixtures/test_audio.ogg", import.meta.url));

test("MIME tables: ALLOWED_MIME is the audio and video sets, without the removed subtitle MIME", () => {
  assert.equal(ALLOWED_MIME.size, AUDIO_MIME.size + VIDEO_MIME.size);
  for (const mime of [...AUDIO_MIME, ...VIDEO_MIME]) assert.ok(ALLOWED_MIME.has(mime), mime);
  assert.equal(ALLOWED_MIME.has("application/x-subrip"), false);
  assert.equal(ALLOWED_MIME.has("text/plain"), false);
});

test("MIME tables: each allowed MIME has an extension", () => {
  for (const mime of ALLOWED_MIME) assert.ok(MIME_TO_EXT[mime], mime);
});

test("MIME tables: the known mappings are the same as the Python MIME_TO_EXT", () => {
  assert.equal(MIME_TO_EXT["audio/mpeg"], ".mp3");
  assert.equal(MIME_TO_EXT["audio/ogg"], ".ogg");
  assert.equal(MIME_TO_EXT["audio/opus"], ".ogg");
  assert.equal(MIME_TO_EXT["application/ogg"], ".ogg");
  assert.equal(MIME_TO_EXT["video/mp4"], ".mp4");
  assert.equal(MIME_TO_EXT["video/quicktime"], ".mov");
  assert.equal(MIME_TO_EXT["video/x-matroska"], ".mkv");
});

test("getExtensionForMime: an unknown MIME gives .bin", () => {
  assert.equal(getExtensionForMime("application/octet-stream"), ".bin");
});

test("sniffMimeFromBytes: Ogg audio is detected as application/ogg", async () => {
  const bytes = new Uint8Array(await readFile(OGG_FIXTURE));
  const mime = await sniffMimeFromBytes(bytes);
  assert.equal(mime, "application/ogg");
  assert.ok(ALLOWED_MIME.has(mime));
  assert.equal(getExtensionForMime(mime), ".ogg");
});

test("sniffMimeFromFile: Ogg audio is detected from the file", async () => {
  assert.equal(await sniffMimeFromFile(OGG_FIXTURE), "application/ogg");
});

test("sniffMimeFromBytes: bytes that are not media give null", async () => {
  assert.equal(await sniffMimeFromBytes(new TextEncoder().encode("not a video ".repeat(10))), null);
});

test("normalizeDetectedMime: Ogg audio with codec parameters is accepted", () => {
  const mime = normalizeDetectedMime("audio/ogg; codecs=opus");
  assert.equal(mime, "audio/ogg");
  assert.ok(ALLOWED_MIME.has(mime));
  assert.equal(getExtensionForMime(mime), ".ogg");
});

test("normalizeDetectedMime: the Matroska and M4A aliases", () => {
  assert.equal(normalizeDetectedMime("video/matroska"), "video/x-matroska");
  assert.equal(normalizeDetectedMime("audio/m4a"), "audio/x-m4a");
  assert.equal(normalizeDetectedMime("VIDEO/MP4"), "video/mp4");
});

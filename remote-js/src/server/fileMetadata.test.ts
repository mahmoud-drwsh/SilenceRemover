// Run: node --test src/server/fileMetadata.test.ts
// The error mapping of the upload metadata insert. Cases from the old
// parity.test.ts (commit 2f1eb5b).
import assert from "node:assert/strict";
import { test } from "node:test";
import { mapUploadMetadataInsertError } from "./fileMetadata.ts";
import { HttpError } from "./schemas.ts";

test("mapUploadMetadataInsertError: a duplicate insert (23505) gives a 409 conflict", () => {
  const error = mapUploadMetadataInsertError({ code: "23505" }, "upload-42");
  assert.ok(error instanceof HttpError);
  assert.equal(error.status, 409);
  assert.equal(error.message, "File with id 'upload-42' already exists");
});

test("mapUploadMetadataInsertError: other database errors stay the same", () => {
  const databaseError = { code: "42P01", message: "missing relation" };
  assert.equal(mapUploadMetadataInsertError(databaseError, "upload-42"), databaseError);
  const plain = new Error("boom");
  assert.equal(mapUploadMetadataInsertError(plain, "upload-42"), plain);
  assert.equal(mapUploadMetadataInsertError(null, "upload-42"), null);
});

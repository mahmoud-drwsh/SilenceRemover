// Run: node --test src/server/adminPaths.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { classifyAdminRequest } from "./adminPaths.ts";

const pass = { kind: "pass" };
const notFound = { kind: "notFound" };
const page = { kind: "page", token: "A" };
const rewrite = (query = "") => ({ kind: "page", token: "A", url: `/admin/A${query}` });

test("other paths pass", () => {
  assert.deepEqual(classifyAdminRequest("GET", "/projects/T/P"), pass);
  assert.deepEqual(classifyAdminRequest("POST", "/admin"), pass);
  assert.deepEqual(classifyAdminRequest("GET", "/admin/"), pass);
  assert.deepEqual(classifyAdminRequest("POST", "/administrator/x"), pass);
});

test("API routes with their own method pass", () => {
  assert.deepEqual(classifyAdminRequest("GET", "/admin/A/api/projects"), pass);
  assert.deepEqual(classifyAdminRequest("HEAD", "/admin/A/api/projects"), pass);
  assert.deepEqual(classifyAdminRequest("GET", "/admin/A/api/projects/s3-storage?x=1"), pass);
  assert.deepEqual(classifyAdminRequest("GET", "/admin/A/api/projects/p%20q/source-processing/status"), pass);
  assert.deepEqual(classifyAdminRequest("POST", "/admin/A/api/refresh-admin-token"), pass);
  assert.deepEqual(classifyAdminRequest("POST", "/admin/A/api/refresh-token"), pass);
  assert.deepEqual(classifyAdminRequest("POST", "/admin/A/api/media-token"), pass);
  assert.deepEqual(classifyAdminRequest("POST", "/admin/A/api/projects/p/source-processing/j/retry"), pass);
});

test("removed files routes pass for every method", () => {
  for (const method of ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]) {
    assert.deepEqual(classifyAdminRequest(method, "/admin/A/files"), pass);
    assert.deepEqual(classifyAdminRequest(method, "/admin/A/files/"), pass);
    assert.deepEqual(classifyAdminRequest(method, "/admin/A/files/x/y"), pass);
  }
});

test("page paths render the page for GET and HEAD", () => {
  assert.deepEqual(classifyAdminRequest("GET", "/admin/A"), page);
  assert.deepEqual(classifyAdminRequest("GET", "/admin/A/"), page);
  assert.deepEqual(classifyAdminRequest("HEAD", "/admin/A/x/y"), page);
});

test("API paths that are not GET routes render the page with a new URL", () => {
  assert.deepEqual(classifyAdminRequest("GET", "/admin/A/api"), rewrite());
  assert.deepEqual(classifyAdminRequest("GET", "/admin/A/api/unknown"), rewrite());
  assert.deepEqual(classifyAdminRequest("GET", "/admin/A/api/refresh-token?x=1"), rewrite("?x=1"));
  assert.deepEqual(classifyAdminRequest("GET", "/admin/A/api/media-token"), rewrite());
  assert.deepEqual(classifyAdminRequest("HEAD", "/admin/A/api/projects/p/source-processing/j/retry"), rewrite());
  assert.deepEqual(classifyAdminRequest("GET", "/admin/A/api/projects/"), rewrite());
});

test("other methods on page paths and unknown API paths get the JSON 404", () => {
  assert.deepEqual(classifyAdminRequest("POST", "/admin/A"), notFound);
  assert.deepEqual(classifyAdminRequest("POST", "/admin/A/"), notFound);
  assert.deepEqual(classifyAdminRequest("OPTIONS", "/admin/A/x"), notFound);
  assert.deepEqual(classifyAdminRequest("POST", "/admin/A/api/unknown"), notFound);
  assert.deepEqual(classifyAdminRequest("POST", "/admin/A/api/projects"), notFound);
  assert.deepEqual(classifyAdminRequest("DELETE", "/admin/A/api/projects/p/source-processing/status"), notFound);
  assert.deepEqual(classifyAdminRequest("POST", "/admin/A/api/media-token/"), notFound);
  assert.deepEqual(classifyAdminRequest("PUT", "/admin/A/api/media-token"), notFound);
});

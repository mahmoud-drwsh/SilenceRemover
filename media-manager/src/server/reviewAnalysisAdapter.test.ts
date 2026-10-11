// Run: node --test src/server/reviewAnalysisAdapter.test.ts
// Port of remote-js/src/routes/reviewAnalysis.test.ts, with more rate-limit
// and error cases.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createReviewAnalysisAdapters, type AdapterDependencies } from "./reviewAnalysisAdapter.ts";
import { HttpError } from "./schemas.ts";

const ogg = new Uint8Array([0x4f, 0x67, 0x67, 0x53, 0x00]);
const ORIGIN = "http://127.0.0.1";
const SNIPPET_PATH = "/projects/project-token/project-a/api/snippet-analysis";
const WORKER_PATH = "/internal/source-processing/project-a/review-analysis";

function deps(overrides: Partial<AdapterDependencies> = {}): AdapterDependencies {
  return {
    verifyMediaToken: async () => {}, verifyWorkerToken: () => {},
    analyze: async () => ({ transcript: "نص عربي", title: "عنوان عربي" }),
    ...overrides,
  };
}

function request(path: string, token = "project-token", bytes: Uint8Array<ArrayBuffer> = ogg, type = "audio/ogg"): Request {
  const form = new FormData();
  form.set("snippet", new File([bytes], "review.ogg", { type }));
  return new Request(`${ORIGIN}${path}`, { method: "POST", headers: { "X-Source-Processing-Token": token }, body: form });
}

test("project and worker adapters return the same canonical result", async () => {
  const adapters = createReviewAnalysisAdapters(deps());
  const publicResponse = await adapters.snippetAnalysis(request(SNIPPET_PATH), "project-token", "project-a");
  const workerResponse = await adapters.reviewAnalysis(request(WORKER_PATH, "worker-token"));
  assert.equal(publicResponse.status, 200);
  assert.equal(workerResponse.status, 200);
  assert.deepEqual(await publicResponse.json(), await workerResponse.json());
});

test("worker adapter rejects a project token", async () => {
  const adapters = createReviewAnalysisAdapters(deps({
    verifyWorkerToken: (token) => { if (token !== "worker-token") throw new Error("no"); },
  }));
  const response = await adapters.reviewAnalysis(request(WORKER_PATH));
  assert.equal(response.status, 401);
  assert.deepEqual(await response.json(), { detail: "Invalid source-processing worker token" });
});

test("project adapter rejects a bad media token with its own text", async () => {
  const adapters = createReviewAnalysisAdapters(deps({
    verifyMediaToken: async () => { throw new HttpError(401, "Invalid token"); },
  }));
  const response = await adapters.snippetAnalysis(request(SNIPPET_PATH), "bad", "project-a");
  assert.equal(response.status, 401);
  assert.deepEqual(await response.json(), { detail: "Invalid media token" });
});

test("public adapter consistently rejects malformed OGG input", async () => {
  const adapters = createReviewAnalysisAdapters(deps());
  const response = await adapters.snippetAnalysis(request(SNIPPET_PATH, "t", new Uint8Array([1, 2, 3])), "project-token", "project-a");
  assert.equal(response.status, 415);
  assert.deepEqual(await response.json(), { detail: "Snippet content is not OGG audio" });
});

test("both adapters reject empty, oversized, and malformed OGG snippets", async () => {
  const adapters = createReviewAnalysisAdapters(deps());
  const empty = await adapters.snippetAnalysis(request(SNIPPET_PATH, "t", new Uint8Array()), "project-token", "project-a");
  assert.equal(empty.status, 413);
  assert.deepEqual(await empty.json(), { detail: "OGG snippet must be no larger than 4 MiB" });
  assert.equal((await adapters.reviewAnalysis(request(WORKER_PATH, "w", new Uint8Array(4 * 1024 * 1024 + 1)))).status, 413);
  assert.equal((await adapters.reviewAnalysis(request(WORKER_PATH, "w", new Uint8Array([1])))).status, 415);
  const wrongType = await adapters.reviewAnalysis(request(WORKER_PATH, "w", ogg, "audio/mpeg"));
  assert.equal(wrongType.status, 415);
  assert.deepEqual(await wrongType.json(), { detail: "Snippet must be audio/ogg" });
  const noFile = new FormData(); noFile.set("snippet", "text");
  const noFileResponse = await adapters.reviewAnalysis(new Request(`${ORIGIN}${WORKER_PATH}`, { method: "POST", body: noFile }));
  assert.equal(noFileResponse.status, 400);
  assert.deepEqual(await noFileResponse.json(), { detail: "snippet file is required" });
});

test("public adapter bounds requests per project token", async () => {
  const adapters = createReviewAnalysisAdapters(deps({ publicRateLimitMax: 1, publicRateLimitWindowMs: 60_000, publicConcurrencyMax: 1 }));
  assert.equal((await adapters.snippetAnalysis(request(SNIPPET_PATH), "project-token", "project-a")).status, 200);
  const limited = await adapters.snippetAnalysis(request(SNIPPET_PATH), "project-token", "project-a");
  assert.equal(limited.status, 429);
  assert.equal(limited.headers.get("Retry-After"), "1");
  assert.deepEqual(await limited.json(), { detail: "Too many snippet-analysis requests" });
  // Another project has its own budget.
  assert.equal((await adapters.snippetAnalysis(request(SNIPPET_PATH), "project-token", "project-b")).status, 200);
});

test("the default policy allows 12 starts in the window and then gives 429", async () => {
  const adapters = createReviewAnalysisAdapters(deps());
  for (let i = 0; i < 12; i += 1) {
    assert.equal((await adapters.snippetAnalysis(request(SNIPPET_PATH), "project-token", "project-a")).status, 200);
  }
  assert.equal((await adapters.snippetAnalysis(request(SNIPPET_PATH), "project-token", "project-a")).status, 429);
});

test("the default policy allows 2 requests at the same time", async () => {
  const gates: Array<() => void> = [];
  const adapters = createReviewAnalysisAdapters(deps({
    analyze: () => new Promise((resolve) => { gates.push(() => resolve({ transcript: "نص", title: "عنوان" })); }),
  }));
  const first = adapters.snippetAnalysis(request(SNIPPET_PATH), "project-token", "project-a");
  const second = adapters.snippetAnalysis(request(SNIPPET_PATH), "project-token", "project-a");
  while (gates.length < 2) await new Promise((resolve) => setTimeout(resolve, 5));
  const third = await adapters.snippetAnalysis(request(SNIPPET_PATH), "project-token", "project-a");
  assert.equal(third.status, 429);
  // The worker adapter has no rate limit.
  const workerGate = adapters.reviewAnalysis(request(WORKER_PATH, "w"));
  while (gates.length < 3) await new Promise((resolve) => setTimeout(resolve, 5));
  for (const open of gates) open();
  assert.equal((await first).status, 200);
  assert.equal((await second).status, 200);
  assert.equal((await workerGate).status, 200);
  // A finished request releases its place.
  const fourth = adapters.snippetAnalysis(request(SNIPPET_PATH), "project-token", "project-a");
  while (gates.length < 4) await new Promise((resolve) => setTimeout(resolve, 5));
  gates[3]!();
  assert.equal((await fourth).status, 200);
});

test("a request that fails releases its place", async () => {
  const adapters = createReviewAnalysisAdapters(deps({
    publicConcurrencyMax: 1,
    analyze: async () => { throw new Error("provider down"); },
  }));
  assert.equal((await adapters.snippetAnalysis(request(SNIPPET_PATH), "project-token", "project-a")).status, 502);
  assert.equal((await adapters.snippetAnalysis(request(SNIPPET_PATH), "project-token", "project-a")).status, 502);
});

test("adapters hide provider failures and malformed multipart input", async () => {
  const adapters = createReviewAnalysisAdapters(deps({
    analyze: async () => { throw new Error("provider secret must not escape"); },
  }));
  const providerFailure = await adapters.snippetAnalysis(request(SNIPPET_PATH), "project-token", "project-a");
  assert.equal(providerFailure.status, 502);
  const text = await providerFailure.text();
  assert.ok(!text.includes("secret"));
  assert.deepEqual(JSON.parse(text), { detail: "Server-side snippet analysis failed" });
  const malformed = await adapters.snippetAnalysis(new Request(`${ORIGIN}${SNIPPET_PATH}`, { method: "POST", body: "not-multipart" }), "project-token", "project-a");
  assert.equal(malformed.status, 400);
  assert.deepEqual(await malformed.json(), { detail: "Expected a multipart OGG snippet" });
});

test("an unconfigured provider gives 503", async () => {
  const adapters = createReviewAnalysisAdapters(deps({
    analyze: async () => { throw new HttpError(503, "Server-side snippet analysis is not configured"); },
  }));
  const response = await adapters.reviewAnalysis(request(WORKER_PATH, "w"));
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { detail: "Server-side snippet analysis is not configured" });
});

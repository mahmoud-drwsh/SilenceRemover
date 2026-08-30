import { expect, test } from "bun:test";
import { createReviewAnalysisRouter } from "./reviewAnalysis.ts";

const ogg = new Uint8Array([0x4f, 0x67, 0x67, 0x53, 0x00]);
const TEST_ORIGIN = "http://127.0.0.1";

function request(path: string, token = "project-token"): Request {
  const form = new FormData();
  form.set("snippet", new File([ogg], "review.ogg", { type: "audio/ogg" }));
  return new Request(`${TEST_ORIGIN}${path}`, { method: "POST", headers: { "X-Source-Processing-Token": token }, body: form });
}

test("project and worker adapters return the same canonical result", async () => {
  const router = createReviewAnalysisRouter({
    verifyMediaToken: async () => {}, verifyWorkerToken: () => {},
    analyze: async () => ({ transcript: "نص عربي", title: "عنوان عربي" }),
  });
  const publicResponse = await router.request(request("/projects/project-token/project-a/api/snippet-analysis"));
  const workerResponse = await router.request(request("/internal/source-processing/project-a/review-analysis", "worker-token"));
  expect(publicResponse.status).toBe(200);
  expect(workerResponse.status).toBe(200);
  await expect(publicResponse.json()).resolves.toEqual(await workerResponse.json());
});

test("worker adapter rejects a project token", async () => {
  const router = createReviewAnalysisRouter({
    verifyMediaToken: async () => {},
    verifyWorkerToken: (token) => { if (token !== "worker-token") throw new Error("no"); },
    analyze: async () => ({ transcript: "نص عربي", title: "عنوان عربي" }),
  });
  const response = await router.request(request("/internal/source-processing/project-a/review-analysis"));
  expect(response.status).toBe(401);
});

test("public adapter consistently rejects malformed OGG input", async () => {
  const router = createReviewAnalysisRouter({ verifyMediaToken: async () => {}, verifyWorkerToken: () => {}, analyze: async () => ({ transcript: "نص", title: "عنوان" }) });
  const form = new FormData();
  form.set("snippet", new File([new Uint8Array([1, 2, 3])], "review.ogg", { type: "audio/ogg" }));
  const response = await router.request(new Request(`${TEST_ORIGIN}/projects/project-token/project-a/api/snippet-analysis`, { method: "POST", body: form }));
  expect(response.status).toBe(415);
  await expect(response.json()).resolves.toEqual({ detail: "Snippet content is not OGG audio" });
});

test("both adapters reject empty, oversized, and malformed OGG snippets", async () => {
  const router = createReviewAnalysisRouter({ verifyMediaToken: async () => {}, verifyWorkerToken: () => {}, analyze: async () => ({ transcript: "نص", title: "عنوان" }) });
  const input = async (path: string, bytes: Uint8Array, type = "audio/ogg") => {
    const form = new FormData(); form.set("snippet", new File([bytes], "review.ogg", { type }));
    return router.request(new Request(`${TEST_ORIGIN}${path}`, { method: "POST", headers: { "X-Source-Processing-Token": "worker-token" }, body: form }));
  };
  expect((await input("/projects/project-token/project-a/api/snippet-analysis", new Uint8Array())).status).toBe(413);
  expect((await input("/internal/source-processing/project-a/review-analysis", new Uint8Array(4 * 1024 * 1024 + 1))).status).toBe(413);
  expect((await input("/internal/source-processing/project-a/review-analysis", new Uint8Array([1]), "audio/ogg")).status).toBe(415);
});

test("public adapter bounds requests per project token", async () => {
  const router = createReviewAnalysisRouter({
    verifyMediaToken: async () => {}, verifyWorkerToken: () => {}, analyze: async () => ({ transcript: "نص", title: "عنوان" }),
    publicRateLimitMax: 1, publicRateLimitWindowMs: 60_000, publicConcurrencyMax: 1,
  });
  expect((await router.request(request("/projects/project-token/project-a/api/snippet-analysis"))).status).toBe(200);
  expect((await router.request(request("/projects/project-token/project-a/api/snippet-analysis"))).status).toBe(429);
});

test("adapters hide provider failures and malformed multipart input", async () => {
  const router = createReviewAnalysisRouter({
    verifyMediaToken: async () => {}, verifyWorkerToken: () => {},
    analyze: async () => { throw new Error("provider secret must not escape"); },
  });
  const providerFailure = await router.request(request("/projects/project-token/project-a/api/snippet-analysis"));
  expect(providerFailure.status).toBe(502);
  expect(await providerFailure.text()).not.toContain("secret");
  const malformed = await router.request(new Request(`${TEST_ORIGIN}/projects/project-token/project-a/api/snippet-analysis`, { method: "POST", body: "not-multipart" }));
  expect(malformed.status).toBe(400);
});

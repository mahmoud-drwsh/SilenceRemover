// Run: node --test src/server/sourceProcessingWorker.test.ts
// The worker token check. The routes themselves are checked by the isolated
// stack flows (source-processing and originals).
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { test } from "node:test";

const BASE_ENV = {
  DATABASE_URL: "postgresql://unused@127.0.0.1:1/unused",
  S3_ENDPOINT_URL: "http://127.0.0.1:1",
  S3_ACCESS_KEY: "unused",
  S3_SECRET_KEY: "unused",
  TOKEN_ENCRYPTION_KEY: "0".repeat(64),
};

/** Run the check in a new process, because loadConfig() keeps its first result. */
function check(workerToken: string | undefined, header: string | null): { status: number | null; stdout: string } {
  const script = `
    import { verifySourceProcessingWorkerToken } from "./src/server/sourceProcessingWorker.ts";
    try { verifySourceProcessingWorkerToken(${JSON.stringify(header)}); console.log("ok"); }
    catch (error) { console.log(error.status + " " + error.message); }`;
  const env: NodeJS.ProcessEnv = { ...process.env, ...BASE_ENV };
  delete env.SOURCE_PROCESSING_WORKER_TOKEN;
  if (workerToken !== undefined) env.SOURCE_PROCESSING_WORKER_TOKEN = workerToken;
  const result = spawnSync(process.execPath, ["--input-type=module", "-e", script], {
    cwd: new URL("../..", import.meta.url), env, encoding: "utf8",
  });
  return { status: result.status, stdout: result.stdout.trim() };
}

test("the configured worker token passes", () => {
  assert.equal(check("worker-secret", "worker-secret").stdout, "ok");
});

test("a missing or wrong worker token gives 401", () => {
  assert.equal(check("worker-secret", null).stdout, "401 Invalid source-processing worker token");
  assert.equal(check("worker-secret", "").stdout, "401 Invalid source-processing worker token");
  assert.equal(check("worker-secret", "worker-secreT").stdout, "401 Invalid source-processing worker token");
  assert.equal(check("worker-secret", "worker-secret-longer").stdout, "401 Invalid source-processing worker token");
});

test("when the worker token is not configured, every worker call gives 401", () => {
  assert.equal(check(undefined, "anything").stdout, "401 Invalid source-processing worker token");
  assert.equal(check("   ", "   ").stdout, "401 Invalid source-processing worker token");
});

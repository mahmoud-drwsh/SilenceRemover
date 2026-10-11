// Run: node --test src/server/auth.test.ts
// The prune step of the login rate limiter.
import assert from "node:assert/strict";
import { test } from "node:test";
import { pruneExpiredAttempts } from "./auth.ts";

test("pruneExpiredAttempts removes keys with no attempt in the window and keeps the others", () => {
  const attempts = new Map<string, number[]>([
    ["old:admin-token", [10, 20]],
    ["mixed:admin-token", [10, 120]],
    ["new:admin-token", [150]],
    ["empty:admin-token", []],
  ]);
  pruneExpiredAttempts(attempts, 100);
  assert.deepEqual([...attempts.keys()].sort(), ["mixed:admin-token", "new:admin-token"]);
  // The prune does not change the stamps of a kept key.
  assert.deepEqual(attempts.get("mixed:admin-token"), [10, 120]);
});

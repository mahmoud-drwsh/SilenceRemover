// Run: node --test src/server/range.test.ts
// The Range header parser of the stream route. Cases from the old
// parity.test.ts (commit 2f1eb5b).
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseRangeHeader } from "./range.ts";

test("parseRangeHeader: no header gives null", () => {
  assert.equal(parseRangeHeader(null, 100), null);
  assert.equal(parseRangeHeader(undefined, 100), null);
  assert.equal(parseRangeHeader("", 100), null);
});

test("parseRangeHeader: a bad shape gives null", () => {
  assert.equal(parseRangeHeader("items=0-10", 100), null);
  assert.equal(parseRangeHeader("bytes=abc", 100), null);
  assert.equal(parseRangeHeader("bytes=0", 100), null);
  assert.equal(parseRangeHeader("bytes=-", 100), null);
  assert.equal(parseRangeHeader("bytes=a-b", 100), null);
});

test("parseRangeHeader: a simple range", () => {
  assert.deepEqual(parseRangeHeader("bytes=0-99", 100), { start: 0, end: 99 });
  assert.deepEqual(parseRangeHeader("bytes=10-20", 100), { start: 10, end: 20 });
  assert.deepEqual(parseRangeHeader("bytes=5-5", 100), { start: 5, end: 5 });
});

test("parseRangeHeader: the end is clamped to size - 1", () => {
  assert.deepEqual(parseRangeHeader("bytes=10-200", 100), { start: 10, end: 99 });
});

test("parseRangeHeader: an open end goes to size - 1", () => {
  assert.deepEqual(parseRangeHeader("bytes=10-", 100), { start: 10, end: 99 });
});

test("parseRangeHeader: a suffix range gives the last bytes", () => {
  assert.deepEqual(parseRangeHeader("bytes=-30", 100), { start: 70, end: 99 });
});

test("parseRangeHeader: a suffix larger than the size starts at 0", () => {
  assert.deepEqual(parseRangeHeader("bytes=-200", 100), { start: 0, end: 99 });
});

test("parseRangeHeader: a zero suffix gives null", () => {
  assert.equal(parseRangeHeader("bytes=-0", 100), null);
});

test("parseRangeHeader: start >= size gives null", () => {
  assert.equal(parseRangeHeader("bytes=100-", 100), null);
  assert.equal(parseRangeHeader("bytes=150-200", 100), null);
});

test("parseRangeHeader: end < start gives null", () => {
  assert.equal(parseRangeHeader("bytes=20-10", 100), null);
});

test("parseRangeHeader: only the first range is used", () => {
  assert.deepEqual(parseRangeHeader("bytes=0-9,20-29", 100), { start: 0, end: 9 });
});

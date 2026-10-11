// Run: node --test src/server/nodeServer.test.ts
// The Node HTTP server rules of server.ts (src/server/http.ts):
// keep-alive timeouts (F1) and the request body limit (F4).
import assert from "node:assert/strict";
import http from "node:http";
import net from "node:net";
import { test } from "node:test";
import { setTimeout as sleep } from "node:timers/promises";
import {
  configureServerTimeouts, DEFAULT_SHUTDOWN_GRACE_MS, drainServer, enforceRequestBodyLimit, MAX_REQUEST_BODY_BYTES,
  shutdownGraceMs,
} from "./http.ts";

type Started = { server: http.Server; port: number };

async function start(limit?: number): Promise<Started> {
  const server = http.createServer((req, res) => {
    if (enforceRequestBodyLimit(req, limit)) return;
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("error", () => {});
    req.on("end", () => {
      const body = JSON.stringify({ received: Buffer.concat(chunks).length });
      res.writeHead(200, { "content-type": "application/json", "content-length": Buffer.byteLength(body) });
      res.end(body);
    });
  });
  configureServerTimeouts(server);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
  return { server, port: (server.address() as net.AddressInfo).port };
}

/** Raw client socket that reads the text that the server sends. */
function connect(port: number): Promise<{ socket: net.Socket; text: () => string; closed: Promise<void> }> {
  return new Promise((resolve) => {
    let received = "";
    const socket = net.connect(port, "127.0.0.1", () => resolve({ socket, text: () => received, closed }));
    socket.on("data", (data) => { received += data.toString("latin1"); });
    socket.on("error", () => {});
    const closed = new Promise<void>((done) => socket.on("close", () => done()));
  });
}

async function waitFor(check: () => boolean, ms = 5000): Promise<void> {
  const end = Date.now() + ms;
  while (!check()) {
    if (Date.now() > end) throw new Error("timed out");
    await sleep(20);
  }
}

test("timeouts: no keep-alive idle timeout, no request timeout", async () => {
  const { server } = await start();
  try {
    assert.equal(server.keepAliveTimeout, 0);
    assert.equal(server.requestTimeout, 0);
    assert.equal(server.timeout, 0);
    assert.ok(server.headersTimeout > 0);
  } finally { server.close(); }
});

test("an idle keep-alive connection that is used again after 10 s still works", { timeout: 30_000 }, async () => {
  const { server, port } = await start();
  try {
    const client = await connect(port);
    const request = "GET / HTTP/1.1\r\nHost: a\r\n\r\n";
    client.socket.write(request);
    await waitFor(() => client.text().includes('{"received":0}'));
    // Node does not send "Keep-Alive: timeout=5" (the old service sent no such header).
    assert.doesNotMatch(client.text(), /keep-alive: timeout/i);
    await sleep(10_500);
    assert.equal(client.socket.destroyed, false, "the server closed the idle connection");
    client.socket.write(request);
    await waitFor(() => client.text().split('{"received":0}').length === 3);
    client.socket.destroy();
  } finally { server.close(); }
});

test("the limit is the old Bun default, 128 MiB", () => {
  assert.equal(MAX_REQUEST_BODY_BYTES, 128 * 1024 * 1024);
});

test("Content-Length above the limit: Bun 413 before the body is read, connection closed", async () => {
  let handled = false;
  const server = http.createServer((req, res) => {
    if (enforceRequestBodyLimit(req, 1000)) return;
    handled = true;
    res.end();
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
  try {
    const client = await connect((server.address() as net.AddressInfo).port);
    client.socket.write("POST / HTTP/1.1\r\nHost: a\r\nContent-Length: 1001\r\n\r\n");
    await client.closed;
    assert.equal(client.text(), "HTTP/1.1 413 Request Entity Too Large\r\nConnection: close\r\n\r\n");
    assert.equal(handled, false);
  } finally { server.close(); }
});

test("Content-Length equal to the limit is accepted", async () => {
  const { server, port } = await start(1000);
  try {
    const client = await connect(port);
    client.socket.write("POST / HTTP/1.1\r\nHost: a\r\nContent-Length: 1000\r\n\r\n" + "a".repeat(1000));
    await waitFor(() => client.text().includes('{"received":1000}'));
    assert.match(client.text(), /^HTTP\/1\.1 200 OK/);
    client.socket.destroy();
  } finally { server.close(); }
});

test("chunked body: reading stops at the limit with the Bun 413", async () => {
  let streamError: Error | undefined;
  let received = 0;
  const server = http.createServer((req) => {
    if (enforceRequestBodyLimit(req, 1000)) return;
    req.on("data", (chunk: Buffer) => { received += chunk.length; });
    req.on("error", (error) => { streamError = error; });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
  try {
    const client = await connect((server.address() as net.AddressInfo).port);
    client.socket.write("POST / HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\n");
    const chunk = "200\r\n" + "a".repeat(512) + "\r\n";
    for (let i = 0; i < 4 && !client.socket.destroyed; i++) {
      client.socket.write(chunk);
      await sleep(50);
    }
    await client.closed;
    assert.equal(client.text(), "HTTP/1.1 413 Payload Too Large\r\nConnection: close\r\n\r\n");
    assert.ok(received <= 1000, `the route received ${received} bytes`);
    assert.match(String(streamError), /maxRequestBodySize/);
  } finally { server.close(); }
});

test("chunked body under the limit is not changed", async () => {
  const { server, port } = await start(1000);
  try {
    const client = await connect(port);
    client.socket.write("POST / HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\n1f4\r\n" + "a".repeat(500) + "\r\n0\r\n\r\n");
    await waitFor(() => client.text().includes('{"received":500}'));
    client.socket.destroy();
  } finally { server.close(); }
});

// Graceful stop (server.ts uses drainServer on SIGTERM and SIGINT).
async function startSlow(delayMs: number): Promise<Started> {
  const server = http.createServer((req, res) => {
    const wait = req.url === "/slow" ? delayMs : 0;
    setTimeout(() => {
      res.writeHead(200, { "content-type": "text/plain", "content-length": 2 });
      res.end("ok");
    }, wait);
  });
  configureServerTimeouts(server);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
  return { server, port: (server.address() as net.AddressInfo).port };
}

test("shutdown grace: default 25 s, SHUTDOWN_GRACE_MS overrides it", () => {
  assert.equal(DEFAULT_SHUTDOWN_GRACE_MS, 25_000);
  assert.equal(shutdownGraceMs(undefined), 25_000);
  assert.equal(shutdownGraceMs(""), 25_000);
  assert.equal(shutdownGraceMs("abc"), 25_000);
  assert.equal(shutdownGraceMs("-1"), 25_000);
  assert.equal(shutdownGraceMs("5000"), 5000);
});

test("drain: a slow request in flight at the stop completes; an idle keep-alive connection closes", { timeout: 15_000 }, async () => {
  const { server, port } = await startSlow(1500);
  const idle = await connect(port);
  idle.socket.write("GET /fast HTTP/1.1\r\nHost: a\r\n\r\n");
  await waitFor(() => idle.text().endsWith("ok"));
  const busy = await connect(port);
  busy.socket.write("GET /slow HTTP/1.1\r\nHost: a\r\n\r\n");
  await sleep(200);
  const started = Date.now();
  const drained = drainServer(server, 10_000);
  // The idle connection closes at once, and a new connection is refused.
  await idle.closed;
  await assert.rejects(new Promise((resolve, reject) => {
    const socket = net.connect(port, "127.0.0.1", () => { socket.destroy(); resolve(null); });
    socket.on("error", reject);
  }));
  assert.equal(await drained, true);
  assert.match(busy.text(), /^HTTP\/1\.1 200 OK/);
  assert.ok(busy.text().endsWith("ok"));
  assert.ok(Date.now() - started >= 1000, "the drain did not wait for the slow request");
  await busy.closed;
});

test("drain: a request slower than the grace time is cut at the grace time", { timeout: 15_000 }, async () => {
  const { server, port } = await startSlow(10_000);
  const busy = await connect(port);
  busy.socket.write("GET /slow HTTP/1.1\r\nHost: a\r\n\r\n");
  await sleep(200);
  const started = Date.now();
  assert.equal(await drainServer(server, 500), false);
  const elapsed = Date.now() - started;
  assert.ok(elapsed >= 450 && elapsed < 3000, `elapsed ${elapsed} ms`);
  await busy.closed;
  assert.equal(busy.text(), "");
});

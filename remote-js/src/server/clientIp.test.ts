// Run: node --test src/server/clientIp.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { isInternalAddress, resolveClientIp } from "./clientIp.ts";

test("no forwarding header: the socket peer is the client", () => {
  assert.equal(resolveClientIp("172.18.0.4", undefined), "172.18.0.4");
  assert.equal(resolveClientIp("::ffff:172.18.0.4", undefined), "172.18.0.4");
  assert.equal(resolveClientIp(undefined, undefined), "unknown");
});

test("internal peer (Traefik): the rightmost X-Forwarded-For entry is the client", () => {
  assert.equal(resolveClientIp("10.0.1.5", "203.0.113.7"), "203.0.113.7");
  // The client sent its own header; Traefik appended the real address.
  assert.equal(resolveClientIp("10.0.1.5", "9.9.9.9, 203.0.113.7"), "203.0.113.7");
  assert.equal(resolveClientIp("10.0.1.5", ["9.9.9.9", "203.0.113.7"]), "203.0.113.7");
  assert.equal(resolveClientIp("::ffff:10.0.1.5", "2001:db8::1"), "2001:db8::1");
  assert.equal(resolveClientIp("127.0.0.1", "198.51.100.2 "), "198.51.100.2");
});

test("public peer: forwarding headers are not trusted", () => {
  assert.equal(resolveClientIp("203.0.113.7", "9.9.9.9"), "203.0.113.7");
  assert.equal(resolveClientIp("2001:db8::7", "9.9.9.9"), "2001:db8::7");
});

test("a bad or empty rightmost entry falls back to the socket peer", () => {
  assert.equal(resolveClientIp("10.0.1.5", "9.9.9.9, not-an-ip"), "10.0.1.5");
  assert.equal(resolveClientIp("10.0.1.5", ""), "10.0.1.5");
  assert.equal(resolveClientIp("10.0.1.5", " , "), "10.0.1.5");
});

test("internal address ranges", () => {
  for (const ip of ["127.0.0.1", "10.1.2.3", "172.16.0.1", "172.31.255.255", "192.168.1.1", "169.254.1.1", "::1", "fd00::1", "fe80::1%eth0", "::ffff:192.168.0.1"]) {
    assert.equal(isInternalAddress(ip), true, ip);
  }
  for (const ip of ["8.8.8.8", "172.15.0.1", "172.32.0.1", "203.0.113.7", "2001:db8::1", "unknown", ""]) {
    assert.equal(isInternalAddress(ip), false, ip);
  }
});

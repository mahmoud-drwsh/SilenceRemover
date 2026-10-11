/**
 * Client IP for the admin-token rate limit and the admin audit log (#63).
 *
 * In production the only path to the app is through Traefik. For each
 * request, Traefik does these steps (pkg/middlewares/forwardedheaders and the
 * Go reverse proxy, default entry-point settings without `trustedIPs`):
 *   1. It removes all X-Forwarded-* and X-Real-Ip headers that the client
 *      sent.
 *   2. It sets X-Real-Ip to the address of the TCP peer that connected to it.
 *   3. The reverse proxy appends the same address to X-Forwarded-For.
 * Step 3 occurs also when `trustedIPs` is set (then the earlier entries come
 * from a trusted proxy in front of Traefik). Thus the RIGHTMOST
 * X-Forwarded-For entry is always the address that Traefik saw. A client can
 * add entries to the LEFT of it, but it cannot change the rightmost entry.
 * X-Real-Ip is safe only when `trustedIPs` is not set, so we do not use it.
 *
 * We use the rightmost entry only when the socket peer is a proxy on an
 * internal network (loopback, private, link-local, or unique-local address).
 * A peer with a public address connects directly, and its forwarding headers
 * are not trusted. If there is no usable entry, the socket peer is the
 * client IP, as in the old service.
 *
 * server.ts calls `resolveClientIp()` with the socket address and puts the
 * result in the CLIENT_IP_HEADER request header. It first removes a copy of
 * that header that the client sent. Route handlers read the header with
 * `requestClientIp()`.
 */

import { isIP } from "node:net";

/** Internal request header. server.ts always replaces the value. */
export const CLIENT_IP_HEADER = "x-media-manager-client-ip";

/** Remove the IPv4-mapped IPv6 prefix ("::ffff:10.0.0.1" -> "10.0.0.1"). */
function unmapIpv4(address: string): string {
  const lower = address.toLowerCase();
  if (lower.startsWith("::ffff:") && isIP(lower.slice(7)) === 4) {
    return lower.slice(7);
  }
  return address;
}

/** Remove brackets and an IPv6 zone ("[fe80::1%eth0]" -> "fe80::1"). */
function cleanAddress(value: string): string {
  let text = value.trim();
  if (text.startsWith("[") && text.endsWith("]")) text = text.slice(1, -1);
  const zone = text.indexOf("%");
  if (zone >= 0) text = text.slice(0, zone);
  return unmapIpv4(text);
}

/**
 * True when the address is loopback, private (RFC 1918), link-local,
 * IPv6 unique-local (fc00::/7), or IPv6 loopback.
 */
export function isInternalAddress(address: string): boolean {
  const ip = cleanAddress(address);
  const family = isIP(ip);
  if (family === 4) {
    const parts = ip.split(".").map(Number);
    const a = parts[0] ?? -1;
    const b = parts[1] ?? -1;
    return (
      a === 127 ||
      a === 10 ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) ||
      (a === 169 && b === 254)
    );
  }
  if (family === 6) {
    const lower = ip.toLowerCase();
    if (lower === "::1") return true;
    const first = Number.parseInt(lower.split(":")[0] || "0", 16);
    return (first & 0xfe00) === 0xfc00 || (first & 0xffc0) === 0xfe80;
  }
  return false;
}

/**
 * The client IP for one request.
 *
 * @param socketPeer the TCP peer address (`req.socket.remoteAddress`).
 * @param forwardedFor the X-Forwarded-For header value(s), if any.
 */
export function resolveClientIp(
  socketPeer: string | undefined,
  forwardedFor: string | string[] | undefined,
): string {
  const peer = socketPeer ? cleanAddress(socketPeer) : "";
  if (peer && isInternalAddress(peer) && forwardedFor !== undefined) {
    const joined = Array.isArray(forwardedFor) ? forwardedFor.join(",") : forwardedFor;
    const entries = joined.split(",").map((entry) => entry.trim()).filter(Boolean);
    const last = entries[entries.length - 1];
    if (last !== undefined) {
      const ip = cleanAddress(last);
      if (isIP(ip) !== 0) return ip;
    }
  }
  return peer || "unknown";
}

/** The client IP that server.ts resolved for this request. */
export function requestClientIp(request: Request): string {
  return request.headers.get(CLIENT_IP_HEADER)?.trim() || "unknown";
}

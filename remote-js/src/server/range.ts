/**
 * HTTP Range header parser - byte-for-byte port of the Python
 * `_parse_range_header` helper in remote/app.py.
 */

export interface ByteRange {
  start: number;
  end: number;
}

/**
 * Parse a `Range: bytes=...` header into inclusive `[start, end]` offsets.
 * Returns null on missing/invalid input or when the requested range falls
 * outside the file size.
 */
export function parseRangeHeader(
  rangeHeader: string | null | undefined,
  size: number,
): ByteRange | null {
  if (!rangeHeader || !rangeHeader.startsWith("bytes=")) {
    return null;
  }
  const rawRange = rangeHeader.slice("bytes=".length).split(",", 1)[0]!.trim();
  if (!rawRange.includes("-")) {
    return null;
  }
  const dashIndex = rawRange.indexOf("-");
  const startRaw = rawRange.slice(0, dashIndex);
  const endRaw = rawRange.slice(dashIndex + 1);

  if (startRaw === "") {
    if (endRaw === "") return null;
    const suffixLen = Number.parseInt(endRaw, 10);
    if (!Number.isFinite(suffixLen) || suffixLen <= 0) return null;
    return { start: Math.max(size - suffixLen, 0), end: size - 1 };
  }

  const start = Number.parseInt(startRaw, 10);
  const end = endRaw === "" ? size - 1 : Number.parseInt(endRaw, 10);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  if (start >= size || end < start) return null;
  return { start, end: Math.min(end, size - 1) };
}

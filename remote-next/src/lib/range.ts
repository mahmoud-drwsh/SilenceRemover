export function parseRangeHeader(
  rangeHeader: string | null,
  size: number,
): [number, number] | null {
  if (!rangeHeader || !rangeHeader.startsWith("bytes=")) return null;
  const rawRange = rangeHeader.slice("bytes=".length).split(",", 1)[0]!.trim();
  if (!rawRange.includes("-")) return null;
  const [startRaw, endRaw] = rawRange.split("-", 2);
  if (startRaw === "") {
    const suffixLen = parseInt(endRaw ?? "", 10);
    if (Number.isNaN(suffixLen) || suffixLen <= 0) return null;
    return [Math.max(size - suffixLen, 0), size - 1];
  }
  const start = parseInt(startRaw, 10);
  const end = endRaw ? parseInt(endRaw, 10) : size - 1;
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  if (start >= size || end < start) return null;
  return [start, Math.min(end, size - 1)];
}

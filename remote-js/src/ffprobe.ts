/**
 * Duration probing via ffprobe. Mirrors the Python upload handler's
 * `subprocess.run(['ffprobe', ...])` block: returns an integer number of
 * seconds, or 0 when ffprobe is missing or fails.
 */

const FFPROBE_TIMEOUT_MS = 10_000;

/**
 * Probe a file's duration in whole seconds via ffprobe. Never throws - any
 * failure (missing binary, parse error, exit code) returns 0 to match the
 * Python `try/except` swallow.
 */
export async function probeDurationSeconds(filePath: string): Promise<number> {
  try {
    const proc = Bun.spawn(
      [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        filePath,
      ],
      {
        stdout: "pipe",
        stderr: "pipe",
      },
    );

    const timeout = setTimeout(() => {
      proc.kill();
    }, FFPROBE_TIMEOUT_MS);

    const exitCode = await proc.exited;
    clearTimeout(timeout);

    if (exitCode !== 0) return 0;

    const text = (await new Response(proc.stdout).text()).trim();
    if (!text) return 0;
    const parsed = Number.parseFloat(text);
    if (!Number.isFinite(parsed)) return 0;
    return Math.trunc(parsed);
  } catch {
    return 0;
  }
}

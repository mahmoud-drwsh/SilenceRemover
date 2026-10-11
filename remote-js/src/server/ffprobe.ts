/**
 * Duration probing via ffprobe (Node.js child_process). Same behavior as
 * remote-js/src/ffprobe.ts: returns whole seconds, or 0 when ffprobe is
 * missing, fails, or runs longer than 10 s.
 */

import { execFile } from "node:child_process";

const FFPROBE_TIMEOUT_MS = 10_000;

/** Probe a file's duration in whole seconds via ffprobe. Never throws. */
export function probeDurationSeconds(filePath: string): Promise<number> {
  return new Promise((resolve) => {
    try {
      execFile(
        "ffprobe",
        ["-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filePath],
        { timeout: FFPROBE_TIMEOUT_MS, killSignal: "SIGKILL", encoding: "utf8", windowsHide: true },
        (error, stdout) => {
          if (error) return resolve(0);
          const text = stdout.trim();
          if (!text) return resolve(0);
          const parsed = Number.parseFloat(text);
          resolve(Number.isFinite(parsed) ? Math.trunc(parsed) : 0);
        },
      );
    } catch {
      resolve(0);
    }
  });
}

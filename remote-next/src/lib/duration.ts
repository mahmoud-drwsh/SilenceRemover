import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export async function probeDurationSeconds(filePath: string): Promise<number> {
  try {
    const { stdout } = await execFileAsync(
      "ffprobe",
      [
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        filePath,
      ],
      { maxBuffer: 1024 * 1024 },
    );
    const n = parseFloat(String(stdout).trim());
    if (Number.isNaN(n)) return 0;
    return Math.floor(n);
  } catch {
    return 0;
  }
}

export const AUDIO_TAGS = new Set(["todo", "ready", "all", "trash"]);

export function parseTags(tagsParam: string | null): string[] | null {
  if (!tagsParam) return null;
  return tagsParam
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

export function validateAudioTags(tags: string[]): string[] {
  const invalid = tags.filter((t) => !AUDIO_TAGS.has(t));
  if (invalid.length) {
    throw new TagsValidationError(
      `Invalid audio tags: ${JSON.stringify(invalid)}. Allowed: ${JSON.stringify([...AUDIO_TAGS])}`,
    );
  }
  return tags;
}

export class TagsValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TagsValidationError";
  }
}

export function normalizeTitle(title: string | null | undefined): string {
  if (title == null) return "";
  return title.trim();
}

export function parseTagsJson(tags: unknown): string[] {
  if (Array.isArray(tags)) {
    return tags.map((t) => String(t));
  }
  if (typeof tags === "string") {
    try {
      const parsed = JSON.parse(tags) as unknown;
      if (Array.isArray(parsed)) return parsed.map((t) => String(t));
    } catch {
      /* fallthrough */
    }
  }
  return [];
}

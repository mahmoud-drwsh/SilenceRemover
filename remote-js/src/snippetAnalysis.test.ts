import { expect, test } from "bun:test";
import { analyzeOggSnippet, type SnippetAnalysisFetcher } from "./routes/snippetAnalysis.ts";

test("analyzeOggSnippet uses dedicated transcription then title APIs", async () => {
  const requests: Array<{ url: string; body: Record<string, unknown>; authorization: string | null }> = [];
  const fakeFetch: SnippetAnalysisFetcher = async (input, init) => {
    requests.push({
      url: String(input),
      body: JSON.parse(String(init?.body)),
      authorization: new Headers(init?.headers).get("Authorization"),
    });
    if (String(input).endsWith("/audio/transcriptions")) {
      return new Response(JSON.stringify({ text: "هذا هو النص" }), { status: 200 });
    }
    return new Response(JSON.stringify({ choices: [{ message: { content: "عنوان الدرس" } }] }), { status: 200 });
  };

  await expect(analyzeOggSnippet(new Uint8Array([0x4f, 0x67, 0x67, 0x53]), {
    apiKey: "server-only-key", baseUrl: "https://provider.invalid/api/v1/",
    transcriptionModel: "stt", titleModel: "title",
  }, fakeFetch)).resolves.toEqual({ transcript: "هذا هو النص", title: "عنوان الدرس" });

  expect(requests).toHaveLength(2);
  expect(requests[0]?.url).toBe("https://provider.invalid/api/v1/audio/transcriptions");
  expect(requests[0]?.authorization).toBe("Bearer server-only-key");
  expect((requests[0]?.body.input_audio as { format: string }).format).toBe("ogg");
  expect(requests[1]?.url).toBe("https://provider.invalid/api/v1/chat/completions");
  expect(JSON.stringify(requests[1]?.body)).toContain("هذا هو النص");
});

test("analyzeOggSnippet rejects an invalid provider title", async () => {
  const fakeFetch: SnippetAnalysisFetcher = async (input) => (
    String(input).endsWith("/audio/transcriptions")
      ? new Response(JSON.stringify({ text: "نص" }), { status: 200 })
      : new Response(JSON.stringify({ choices: [{ message: { content: "عنوان\nثان" } }] }), { status: 200 })
  );
  await expect(analyzeOggSnippet(new Uint8Array([0x4f, 0x67, 0x67, 0x53]), {
    apiKey: "key", baseUrl: "https://provider.invalid/api/v1",
    transcriptionModel: "stt", titleModel: "title",
  }, fakeFetch)).rejects.toThrow("invalid title");
});

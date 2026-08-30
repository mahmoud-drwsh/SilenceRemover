import { expect, test } from "bun:test";
import { analyzeReviewOgg, type ReviewAnalysisFetcher } from "./reviewAnalysis.ts";

const arabicGolden = await Bun.file(new URL("./fixtures/review-analysis-arabic.json", import.meta.url)).json() as {
  transcript: string; title: string;
};
const PROVIDER_BASE_URL = "http://127.0.0.1/api/v1";

test("analyzeReviewOgg returns the canonical Arabic golden result", async () => {
  const fakeFetch: ReviewAnalysisFetcher = async (input) => (
    String(input).endsWith("/audio/transcriptions")
      ? new Response(JSON.stringify({ text: arabicGolden.transcript }))
      : new Response(JSON.stringify({ choices: [{ message: { content: arabicGolden.title } }] }))
  );

  await expect(analyzeReviewOgg(new Uint8Array([0x4f, 0x67, 0x67, 0x53]), {
    apiKey: "test-key", baseUrl: PROVIDER_BASE_URL,
    transcriptionModel: "arabic-stt", titleModel: "arabic-title",
  }, fakeFetch)).resolves.toEqual(arabicGolden);
});

test("analyzeReviewOgg retries a bounded transient provider failure", async () => {
  let transcriptionAttempts = 0;
  const fakeFetch: ReviewAnalysisFetcher = async (input) => {
    if (String(input).endsWith("/audio/transcriptions")) {
      transcriptionAttempts += 1;
      if (transcriptionAttempts === 1) return new Response("busy", { status: 503 });
      return new Response(JSON.stringify({ text: arabicGolden.transcript }));
    }
    return new Response(JSON.stringify({ choices: [{ message: { content: arabicGolden.title } }] }));
  };
  await expect(analyzeReviewOgg(new Uint8Array([0x4f, 0x67, 0x67, 0x53]), {
    apiKey: "test-key", baseUrl: PROVIDER_BASE_URL, transcriptionModel: "stt", titleModel: "title", maxAttempts: 2,
  }, fakeFetch)).resolves.toEqual(arabicGolden);
  expect(transcriptionAttempts).toBe(2);
});

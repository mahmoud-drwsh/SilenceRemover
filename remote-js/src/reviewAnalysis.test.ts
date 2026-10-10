import { expect, test } from "bun:test";
import { analyzeReviewOgg, oggDurationSeconds, ReviewAnalysisError, type ReviewAnalysisFetcher } from "./reviewAnalysis.ts";

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

function oggWithDuration(seconds: number): Uint8Array {
  const page = new Uint8Array(27);
  page.set([0x4f, 0x67, 0x67, 0x53, 0, 4]);
  new DataView(page.buffer).setBigInt64(6, BigInt(seconds * 48_000), true);
  return page;
}

const titleResponse = () => new Response(JSON.stringify({ choices: [{ message: { content: arabicGolden.title } }] }));

test("oggDurationSeconds reads the last Opus granule position", () => {
  expect(oggDurationSeconds(oggWithDuration(90))).toBe(90);
  expect(oggDurationSeconds(new Uint8Array([1, 2, 3]))).toBeNull();
});

test("a chat: transcription model sends the audio to chat completions", async () => {
  const bodies: Array<{ url: string; body: any }> = [];
  const fakeFetch: ReviewAnalysisFetcher = async (input, init) => {
    const body = JSON.parse(String(init?.body));
    bodies.push({ url: String(input), body });
    if (Array.isArray(body.messages[0].content)) {
      return new Response(JSON.stringify({ choices: [{ message: { content: arabicGolden.transcript } }] }));
    }
    return titleResponse();
  };
  await expect(analyzeReviewOgg(new Uint8Array([0x4f, 0x67, 0x67, 0x53]), {
    apiKey: "k", baseUrl: PROVIDER_BASE_URL, transcriptionModel: "chat:google/audio-chat", titleModel: "title",
  }, fakeFetch)).resolves.toEqual(arabicGolden);
  expect(bodies[0]!.url).toEndWith("/chat/completions");
  expect(bodies[0]!.body.model).toBe("google/audio-chat");
  expect(bodies[0]!.body.messages[0].content[1].input_audio.format).toBe("ogg");
});

test("a removed transcription model falls back to the fallback model", async () => {
  const models: string[] = [];
  const fakeFetch: ReviewAnalysisFetcher = async (input, init) => {
    const body = JSON.parse(String(init?.body));
    models.push(body.model);
    if (String(input).endsWith("/audio/transcriptions")) {
      return body.model === "gone" ? new Response("{}", { status: 404 }) : new Response(JSON.stringify({ text: arabicGolden.transcript }));
    }
    return titleResponse();
  };
  await expect(analyzeReviewOgg(new Uint8Array([1]), {
    apiKey: "k", baseUrl: PROVIDER_BASE_URL, transcriptionModel: "gone", transcriptionFallbackModel: "backup", titleModel: "title",
  }, fakeFetch)).resolves.toEqual(arabicGolden);
  expect(models).toEqual(["gone", "backup", "title"]);
});

test("an empty title from the main model uses the title fallback", async () => {
  const fakeFetch: ReviewAnalysisFetcher = async (input, init) => {
    if (String(input).endsWith("/audio/transcriptions")) return new Response(JSON.stringify({ text: arabicGolden.transcript }));
    const model = JSON.parse(String(init?.body)).model;
    return model === "main" ? new Response(JSON.stringify({ choices: [{ message: { content: "" } }] })) : titleResponse();
  };
  await expect(analyzeReviewOgg(new Uint8Array([1]), {
    apiKey: "k", baseUrl: PROVIDER_BASE_URL, transcriptionModel: "stt", titleModel: "main", titleFallbackModel: "backup",
  }, fakeFetch)).resolves.toEqual(arabicGolden);
});

test.each([
  ["a short summary", "ملخص قصير"],
  ["an English reply", "This audio is a religious lesson about prayer and purity in Islam. ".repeat(20)],
])("a chat transcript that is %s falls back to the transcription endpoint", async (_label, chatText) => {
  const transcript = "هذا نص عربي طويل من الدرس. ".repeat(40);
  const fakeFetch: ReviewAnalysisFetcher = async (input, init) => {
    const body = JSON.parse(String(init?.body));
    if (String(input).endsWith("/audio/transcriptions")) return new Response(JSON.stringify({ text: transcript }));
    if (Array.isArray(body.messages[0].content)) return new Response(JSON.stringify({ choices: [{ message: { content: chatText } }] }));
    return titleResponse();
  };
  const result = await analyzeReviewOgg(oggWithDuration(100), {
    apiKey: "k", baseUrl: PROVIDER_BASE_URL, transcriptionModel: "chat:audio", transcriptionFallbackModel: "stt", titleModel: "title",
  }, fakeFetch);
  expect(result.transcript).toBe(transcript.trim());
});

test("the total deadline stops retries before the caller gives up", async () => {
  let calls = 0;
  const fakeFetch: ReviewAnalysisFetcher = async (_input, init) => {
    calls += 1;
    return await new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new Error("aborted")));
    });
  };
  const started = Date.now();
  await expect(analyzeReviewOgg(new Uint8Array([1]), {
    apiKey: "k", baseUrl: PROVIDER_BASE_URL, transcriptionModel: "a", transcriptionFallbackModel: "b", titleModel: "t",
    timeoutMs: 60_000, maxAttempts: 3, deadlineMs: 1_500,
  }, fakeFetch)).rejects.toThrow(ReviewAnalysisError);
  expect(Date.now() - started).toBeLessThan(3_000);
  expect(calls).toBe(1);
});

// Run: node --test src/server/reviewAnalysis.test.ts
// Port of remote-js/src/reviewAnalysis.test.ts and snippetAnalysis.test.ts.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { analyzeReviewOgg, oggDurationSeconds, ReviewAnalysisError, type ReviewAnalysisFetcher } from "./reviewAnalysis.ts";

const arabicGolden = JSON.parse(readFileSync(new URL("./fixtures/review-analysis-arabic.json", import.meta.url), "utf8")) as {
  transcript: string; title: string;
};
const PROVIDER_BASE_URL = "http://127.0.0.1/api/v1";

test("analyzeReviewOgg returns the canonical Arabic golden result", async () => {
  const fakeFetch: ReviewAnalysisFetcher = async (input) => (
    String(input).endsWith("/audio/transcriptions")
      ? new Response(JSON.stringify({ text: arabicGolden.transcript }))
      : new Response(JSON.stringify({ choices: [{ message: { content: arabicGolden.title } }] }))
  );

  assert.deepEqual(await analyzeReviewOgg(new Uint8Array([0x4f, 0x67, 0x67, 0x53]), {
    apiKey: "test-key", baseUrl: PROVIDER_BASE_URL,
    transcriptionModel: "arabic-stt", titleModel: "arabic-title",
  }, fakeFetch), arabicGolden);
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
  assert.deepEqual(await analyzeReviewOgg(new Uint8Array([0x4f, 0x67, 0x67, 0x53]), {
    apiKey: "test-key", baseUrl: PROVIDER_BASE_URL, transcriptionModel: "stt", titleModel: "title", maxAttempts: 2,
  }, fakeFetch), arabicGolden);
  assert.equal(transcriptionAttempts, 2);
});

function oggWithDuration(seconds: number): Uint8Array {
  const page = new Uint8Array(27);
  page.set([0x4f, 0x67, 0x67, 0x53, 0, 4]);
  new DataView(page.buffer).setBigInt64(6, BigInt(seconds * 48_000), true);
  return page;
}

const titleResponse = () => new Response(JSON.stringify({ choices: [{ message: { content: arabicGolden.title } }] }));

test("oggDurationSeconds reads the last Opus granule position", () => {
  assert.equal(oggDurationSeconds(oggWithDuration(90)), 90);
  assert.equal(oggDurationSeconds(new Uint8Array([1, 2, 3])), null);
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
  assert.deepEqual(await analyzeReviewOgg(new Uint8Array([0x4f, 0x67, 0x67, 0x53]), {
    apiKey: "k", baseUrl: PROVIDER_BASE_URL, transcriptionModel: "chat:google/audio-chat", titleModel: "title",
  }, fakeFetch), arabicGolden);
  assert.ok(bodies[0]!.url.endsWith("/chat/completions"));
  assert.equal(bodies[0]!.body.model, "google/audio-chat");
  assert.equal(bodies[0]!.body.messages[0].content[1].input_audio.format, "ogg");
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
  assert.deepEqual(await analyzeReviewOgg(new Uint8Array([1]), {
    apiKey: "k", baseUrl: PROVIDER_BASE_URL, transcriptionModel: "gone", transcriptionFallbackModel: "backup", titleModel: "title",
  }, fakeFetch), arabicGolden);
  assert.deepEqual(models, ["gone", "backup", "title"]);
});

test("an empty title from the main model uses the title fallback", async () => {
  const fakeFetch: ReviewAnalysisFetcher = async (input, init) => {
    if (String(input).endsWith("/audio/transcriptions")) return new Response(JSON.stringify({ text: arabicGolden.transcript }));
    const model = JSON.parse(String(init?.body)).model;
    return model === "main" ? new Response(JSON.stringify({ choices: [{ message: { content: "" } }] })) : titleResponse();
  };
  assert.deepEqual(await analyzeReviewOgg(new Uint8Array([1]), {
    apiKey: "k", baseUrl: PROVIDER_BASE_URL, transcriptionModel: "stt", titleModel: "main", titleFallbackModel: "backup",
  }, fakeFetch), arabicGolden);
});

for (const [label, chatText] of [
  ["a short summary", "ملخص قصير"],
  ["an English reply", "This audio is a religious lesson about prayer and purity in Islam. ".repeat(20)],
] as const) test(`a chat transcript that is ${label} falls back to the transcription endpoint`, async () => {
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
  assert.equal(result.transcript, transcript.trim());
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
  // Node does not keep the process alive for AbortSignal.timeout (Bun does).
  const keepAlive = setInterval(() => {}, 1_000);
  try {
    await assert.rejects(analyzeReviewOgg(new Uint8Array([1]), {
      apiKey: "k", baseUrl: PROVIDER_BASE_URL, transcriptionModel: "a", transcriptionFallbackModel: "b", titleModel: "t",
      timeoutMs: 60_000, maxAttempts: 3, deadlineMs: 3_000,
    }, fakeFetch), ReviewAnalysisError);
  } finally {
    clearInterval(keepAlive);
  }
  // Transcription gets half of a short deadline; the rest is kept for the title.
  assert.ok(Date.now() - started < 2_500);
  assert.equal(calls, 1);
});

test("the transcription endpoint text is kept even when it is short", async () => {
  const fakeFetch: ReviewAnalysisFetcher = async (input) => (
    String(input).endsWith("/audio/transcriptions") ? new Response(JSON.stringify({ text: "نشيد" })) : titleResponse()
  );
  assert.deepEqual(await analyzeReviewOgg(oggWithDuration(100), {
    apiKey: "k", baseUrl: PROVIDER_BASE_URL, transcriptionModel: "stt", titleModel: "title",
  }, fakeFetch), { transcript: "نشيد", title: arabicGolden.title });
});

test("a null provider body uses the fallback model", async () => {
  const fakeFetch: ReviewAnalysisFetcher = async (input, init) => {
    if (String(input).endsWith("/audio/transcriptions")) return new Response(JSON.stringify({ text: arabicGolden.transcript }));
    return JSON.parse(String(init?.body)).model === "main" ? new Response("null") : titleResponse();
  };
  assert.deepEqual(await analyzeReviewOgg(new Uint8Array([1]), {
    apiKey: "k", baseUrl: PROVIDER_BASE_URL, transcriptionModel: "stt", titleModel: "main", titleFallbackModel: "backup",
  }, fakeFetch), arabicGolden);
});

test("diacritics do not count toward the chat transcript length", async () => {
  // 35 characters per second with full tashkeel is 20 without it.
  const vocalized = "بِسْمِ ".repeat(300);
  const fakeFetch: ReviewAnalysisFetcher = async (input, init) => {
    const body = JSON.parse(String(init?.body));
    if (Array.isArray(body.messages[0].content)) return new Response(JSON.stringify({ choices: [{ message: { content: vocalized } }] }));
    return titleResponse();
  };
  const result = await analyzeReviewOgg(oggWithDuration(60), {
    apiKey: "k", baseUrl: PROVIDER_BASE_URL, transcriptionModel: "chat:audio", titleModel: "title",
  }, fakeFetch);
  assert.equal(result.transcript, vocalized.trim());
});

// From remote-js/src/snippetAnalysis.test.ts (the old compatibility names).

test("analyzeReviewOgg uses dedicated transcription then title APIs", async () => {
  const requests: Array<{ url: string; body: Record<string, unknown>; authorization: string | null }> = [];
  const fakeFetch: ReviewAnalysisFetcher = async (input, init) => {
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

  assert.deepEqual(await analyzeReviewOgg(new Uint8Array([0x4f, 0x67, 0x67, 0x53]), {
    apiKey: "server-only-key", baseUrl: "https://provider.invalid/api/v1/",
    transcriptionModel: "stt", titleModel: "title",
  }, fakeFetch), { transcript: "هذا هو النص", title: "عنوان الدرس" });

  assert.equal(requests.length, 2);
  assert.equal(requests[0]?.url, "https://provider.invalid/api/v1/audio/transcriptions");
  assert.equal(requests[0]?.authorization, "Bearer server-only-key");
  assert.equal((requests[0]?.body.input_audio as { format: string }).format, "ogg");
  assert.equal(requests[1]?.url, "https://provider.invalid/api/v1/chat/completions");
  assert.ok(JSON.stringify(requests[1]?.body).includes("هذا هو النص"));
});

test("analyzeReviewOgg rejects an invalid provider title", async () => {
  const fakeFetch: ReviewAnalysisFetcher = async (input) => (
    String(input).endsWith("/audio/transcriptions")
      ? new Response(JSON.stringify({ text: "نص" }), { status: 200 })
      : new Response(JSON.stringify({ choices: [{ message: { content: "عنوان\nثان" } }] }), { status: 200 })
  );
  await assert.rejects(analyzeReviewOgg(new Uint8Array([0x4f, 0x67, 0x67, 0x53]), {
    apiKey: "key", baseUrl: "https://provider.invalid/api/v1",
    transcriptionModel: "stt", titleModel: "title",
  }, fakeFetch), /invalid title/);
});

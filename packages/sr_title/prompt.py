"""LLM prompt templates for title generation."""

__all__ = [
    "TITLE_PROMPT_TEMPLATE",
    "TITLE_CANDIDATES_PROMPT_TEMPLATE",
    "TITLE_CANDIDATES_SCORE_PROMPT_TEMPLATE",
]

TITLE_PROMPT_TEMPLATE = """\
Generate one YouTube video title in Arabic from the transcript below. The title must be in Arabic. Output only the title text on one line, with no commentary, explanation, quotes, or extra text.

The title is expected near the beginning of the transcript, usually within the first few complete sentences. Extract the title only from those opening title-introduction sentences.

Rules:
1. Verbatim only: the title must be copied as one contiguous span from the transcript, using the exact same Arabic words in the same order.
2. Opening only: use only the first few complete sentences where the title is introduced.
3. Skip prefatory invocations: do not choose a title that is only a formulaic opening invocation, prayer, praise, greeting, or blessing, such as "بسم الله الرحمن الرحيم", "الحمد لله", "الصلاة والسلام على رسول الله", "السلام عليكم", or similar generic opening phrases.
4. Narrow exclusion: do not reject a meaningful title merely because it contains religious words. Only reject the phrase when it functions as a standalone prefatory opening rather than the actual subject/title.
5. Lesson/book pattern: if the opening title-introduction sentences explicitly contain a lesson number together with a book, series, or course title, prefer a title that includes both parts in one verbatim span. Examples of this pattern include phrases like "الدرس الثامن من سلسلة دروس منتقى الأخبار", "الدرس الحادي والثلاثين من سلسلة دروس أحكام القرآن", or "الدرس الثامن من سلسلة دروس بداية المجتهد ونهاية المقتصد".
6. Conditional use only: apply the lesson/book pattern only when it is explicitly present in the transcript. Do not invent a lesson number, book name, series name, or course title.
7. Reject later content: do not use phrases from later explanation, answer, commentary, or body text, even if they sound like good titles.
8. No added words: do not add labels such as "العنوان", "عنوان الفيديو", "Title:", quotes, punctuation wrappers, or explanatory words.
9. Natural span: prefer a complete, natural title-like phrase from the opening sentences after any prefatory invocation.
10. Length: the title must be suitable for YouTube, up to 100 characters.
11. If shortening is needed, remove only leading or trailing words from the same verbatim opening span.

Transcript:
{transcript}
"""

# Used by `sr_title.api` for one-shot candidate pool generation (JSON array output).
TITLE_CANDIDATES_PROMPT_TEMPLATE = """\
Generate exactly {candidate_count} distinct YouTube video title candidates in Arabic from the transcript below.

The title is expected near the beginning of the transcript, usually within the first few complete sentences. Extract candidates only from those opening title-introduction sentences.

Output format:
- Output only a single valid JSON array of exactly {candidate_count} strings.
- No markdown, no code fences, no commentary, and no text before or after the JSON array.
- Each string must be one line.
- All {candidate_count} titles must be different.

Rules for every title:
1. Verbatim only: each title must be copied as one contiguous span from the transcript, using the exact same Arabic words in the same order.
2. Opening only: use only the first few complete sentences where the title is introduced.
3. Skip prefatory invocations: do not choose a title that is only a formulaic opening invocation, prayer, praise, greeting, or blessing, such as "بسم الله الرحمن الرحيم", "الحمد لله", "الصلاة والسلام على رسول الله", "السلام عليكم", or similar generic opening phrases.
4. Narrow exclusion: do not reject a meaningful title merely because it contains religious words. Only reject the phrase when it functions as a standalone prefatory opening rather than the actual subject/title.
5. Lesson/book pattern: if the opening title-introduction sentences explicitly contain a lesson number together with a book, series, or course title, prefer candidates that include both parts in one verbatim span. Examples of this pattern include phrases like "الدرس الثامن من سلسلة دروس منتقى الأخبار", "الدرس الحادي والثلاثين من سلسلة دروس أحكام القرآن", or "الدرس الثامن من سلسلة دروس بداية المجتهد ونهاية المقتصد".
6. Conditional use only: apply the lesson/book pattern only when it is explicitly present in the transcript. Do not invent a lesson number, book name, series name, or course title.
7. Reject later content: do not use phrases from later explanation, answer, commentary, or body text, even if they sound like good titles.
8. No added words: do not add labels such as "العنوان", "عنوان الفيديو", "Title:", quotes, punctuation wrappers, or explanatory words.
9. Natural span: prefer a complete, natural title-like phrase from the opening sentences after any prefatory invocation.
10. Length: each title must be suitable for YouTube, up to 100 characters.
11. If shortening is needed, remove only leading or trailing words from the same verbatim opening span.

Vary the chosen spans when possible. If a lesson/book pattern is present, include at least one candidate that preserves the lesson number and book/series title together. Otherwise, use the best natural title-like spans from the opening sentences.

Transcript:
{transcript}
"""

# Used by `sr_title.api` for one-shot scoring of all candidates (JSON object output).
TITLE_CANDIDATES_SCORE_PROMPT_TEMPLATE = """\
You evaluate Arabic video title candidates against a transcript. Score every candidate in order.

The correct title is expected near the beginning of the transcript, usually within the first few complete sentences. A good candidate must be copied verbatim from that opening title-introduction region, after any standalone prefatory invocation or greeting.

Transcript:
{transcript}

Candidates (JSON array, fixed order; evaluation index i corresponds to candidates[i]):
{candidates_json}

For each candidate, output two integer scores from 0 to 10:

1) verbatim_score:
How well the candidate matches one contiguous verbatim span from the transcript.
- 10: exact contiguous transcript span, with only minor punctuation or whitespace differences.
- 5-9: mostly verbatim, but has small wording, punctuation, or boundary issues.
- 0-4: not a contiguous transcript span, paraphrased, invented, or contains added words.

2) correctness_score:
How well the candidate behaves like the actual title from the opening title-introduction sentences.
- 10: clean title-like phrase from the first few complete sentences after any standalone prefatory invocation. If the opening explicitly contains a lesson number with a book, series, or course title, a 10 should usually include both the lesson number and that book/series/course title.
- 5-9: mostly from the opening region, but missing useful structured title information, slightly too broad, too short, awkwardly cut, or has minor formatting issues.
- 0-4: taken from later explanation/body text, not title-like, includes labels/commentary, violates the opening-only rule, invents lesson/book details, or is only a formulaic prefatory invocation/prayer/greeting.

Hard scoring rules:
- If the candidate is not verbatim, verbatim_score must be 4 or lower.
- If the candidate appears only after the opening title-introduction sentences, correctness_score must be 4 or lower.
- If the candidate adds words not present in the transcript, verbatim_score must be 4 or lower.
- If the candidate invents or changes a lesson number, book name, series name, or course title, verbatim_score must be 4 or lower.
- If the transcript opening clearly contains a phrase like "الدرس ..." together with "من سلسلة دروس ..." or another explicit book/series/course title, candidates that omit either the lesson number or the book/series/course title should score lower than an otherwise clean candidate that includes both.
- If the candidate includes labels such as "العنوان", "عنوان الفيديو", or "Title:", correctness_score must be 4 or lower.
- If the candidate is only a standalone prefatory invocation, prayer, praise, greeting, or blessing, such as "بسم الله الرحمن الرحيم", "الحمد لله", "الصلاة والسلام على رسول الله", "السلام عليكم", or similar generic opening phrasing, correctness_score must be 4 or lower.
- Do not penalize a meaningful subject/title phrase merely because it contains religious vocabulary; penalize only generic prefatory openings that are not the actual title.

Output format:
- Output only one valid JSON object.
- No markdown, no code fences, no commentary.
- Shape: {{"evaluations":[{{"verbatim_score":int,"correctness_score":int}}, ...]}}
- The evaluations array must have exactly the same length as the Candidates array, in the same order.
- Each score must be an integer from 0 through 10.
"""

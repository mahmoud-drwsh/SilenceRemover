"""Configuration constants and environment variables for video processing."""

import os

# --- Trimming Constants ---

MAX_PAD_SEC = 10.0
PAD_INCREMENT_SEC = 0.01
BITRATE_FALLBACK_BPS = 3_000_000
AUDIO_BITRATE = "192k"
PREFERRED_VIDEO_ENCODERS = [
    "hevc_qsv",
    "h264_qsv",
    "h264_videotoolbox",
    "h264_amf",
]

# --- OpenRouter API Configuration ---
# (configurable via environment variables)

OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_DEFAULT_MODEL = os.getenv("OPENROUTER_DEFAULT_MODEL", "google/gemini-2.0-flash-lite-001")

# Title generation model
OPENROUTER_TITLE_MODEL = os.getenv("OPENROUTER_TITLE_MODEL", "openai/gpt-oss-120b")

# --- AI Prompts ---

TRANSCRIBE_PROMPT = """Transcribe the Arabic audio as clean verbatim text in Arabic.
- No timestamps
- No speaker labels
- Keep punctuation and natural phrasing."""

TITLE_PROMPT_TEMPLATE = """\
Generate a YouTube video title in Arabic based on the Arabic transcript below.

⚠️ CRITICAL REQUIREMENT - HONORIFICS (MUST FOLLOW):
You MUST include ﷺ immediately after EVERY mention of Prophet Muhammad in the title.
This applies to ANY reference including: محمد, رسول الله, المصطفى, النبي, سيدنا رسول الله, سيدنا محمد, النبي محمد, رسول الله صلى الله عليه وسلم, etc.
If the transcript mentions the Prophet, the title MUST include ﷺ after that mention.
This is non-negotiable and must be followed in every single title.

REQUIREMENTS:
1. Maximum 100 characters (strict limit) - but aim for 60-90 characters for better descriptiveness
2. Accurately reflect the main topic/content discussed in the transcript
3. Be descriptive and informative - include key details from the transcript
4. Use words from the transcript verbatim when possible
5. Title only - no quotes, no extra commentary, no explanations
6. ⚠️ If Prophet Muhammad is mentioned, you MUST add ﷺ after that mention

FORMATTING RULES:
- Make the topic part descriptive enough to understand what is discussed

EXAMPLES (Note: ALL examples with Prophet mentions include ﷺ):
- تعظيم الإمام مالك لسيدنا رسول الله ﷺ
- كتاب الشفاء بتعريف حقوق المصطفى ﷺ

Arabic transcript:
{transcript}

Generate ONE title only (60-90 characters recommended, max 100, accurately reflecting the Arabic transcript content):
Remember: If the transcript mentions Prophet Muhammad in any way, you MUST include ﷺ after that mention.
"""

# --- File Type Constants ---

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ogv", ".ts", ".m2ts",
}

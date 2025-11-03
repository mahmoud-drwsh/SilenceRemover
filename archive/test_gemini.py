#!/usr/bin/env python3
"""
Simple script to test Gemini API integration.

NOTE: This script strictly follows the official Gemini API documentation pattern.
Reference: https://ai.google.dev/gemini-api/docs
"""

# To run this code you need to install the following dependencies:
# pip install google-genai

import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables from .env file
load_dotenv()


def generate():
    """
    Generate content using Gemini API.
    Strictly follows the official documentation pattern.
    """
    client = genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY"),
    )

    model = "gemini-2.5-pro"
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text="""Say hello and confirm you're working!"""),
            ],
        ),
    ]

    generate_content_config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(
            thinking_budget=-1,
        ),
    )

    for chunk in client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=generate_content_config,
    ):
        print(chunk.text, end="")


if __name__ == "__main__":
    generate()

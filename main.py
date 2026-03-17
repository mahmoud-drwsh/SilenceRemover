#!/usr/bin/env python3
import sys
from pathlib import Path

# Load .env file BEFORE any imports that might use config
from dotenv import load_dotenv

load_dotenv()

# Ensure project root (where this file lives) is on sys.path so `src` package is importable
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.pipeline import run


if __name__ == "__main__":
    run()

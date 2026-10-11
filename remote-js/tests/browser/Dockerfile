# Browser tests (Playwright for Python) for the isolated test stack.
# Base image: mcr.microsoft.com/playwright/python:v1.63.0-noble (published
# 2026-09-15), pinned by the digest of its multi-platform index. It has
# Python 3.12 and the browsers for Playwright 1.63.0. The Python package is
# installed from requirements.txt (exact versions, wheel hashes, no source
# builds, so no install scripts run).
# The tests seed rows with psql, so the image adds the PostgreSQL client
# from the Ubuntu archive. The test network has no internet access, so all
# tools must be in the image.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble@sha256:72bd171a9ffc2b4b59532aaa6210e21014d07093120dc25528870c0b840da1f0

RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages --require-hashes --only-binary :all: --no-deps \
      -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /tests
CMD ["python", "-m", "unittest", "discover", "-s", "/tests", "-p", "test_*.py", "-v"]

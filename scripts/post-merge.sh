#!/bin/bash
set -e

# Install Python dependencies
pip install -e ".[dev]" --quiet

# Install JS dependencies for remote-js
cd remote-js && bun install --frozen-lockfile

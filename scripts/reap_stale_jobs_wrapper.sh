#!/bin/bash
# Wrapper script for reap_stale_jobs.py - run from project root
set -e
cd ~/Projects/youtube-transcriber
source .venv-native/bin/activate
python scripts/reap_stale_jobs.py "$@"

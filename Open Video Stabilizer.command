#!/bin/zsh
set -e
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Setting up Video Stabilizer for the first time..."
  python3 -m venv .venv
fi
if [[ ! -x .venv/bin/video-stabilizer-ui ]] || ! .venv/bin/python -c 'import streamlit' >/dev/null 2>&1; then
  echo "Installing the browser interface. First-time setup needs an internet connection."
  .venv/bin/python -m pip install -e '.[ui]'
fi
echo "Opening Video Stabilizer. Keep this window open while using the app."
exec .venv/bin/video-stabilizer-ui

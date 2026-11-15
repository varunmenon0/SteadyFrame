#!/bin/zsh
set -e
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Setting up SteadyFrame for the first time..."
  python3 -m venv .venv
fi
if [[ ! -x .venv/bin/steadyframe-ui ]] || ! .venv/bin/python -c 'import streamlit' >/dev/null 2>&1; then
  echo "Installing the browser interface. First-time setup needs an internet connection."
  .venv/bin/python -m pip install -e '.[ui]'
fi
echo "Opening SteadyFrame. Keep this window open while using the app."
exec .venv/bin/steadyframe-ui

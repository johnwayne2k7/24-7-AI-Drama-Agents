#!/bin/bash
# 24/7 Drama Bots launcher for Mac: double-click this file.
cd "$(dirname "$0")" || exit 1
PORT="${PORT:-4247}"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install it from https://www.python.org/downloads/ and try again."
  read -r -p "Press Enter to close."
  exit 1
fi
[ -f .env ] || cp .env.example .env
echo "24/7 Drama Bots is starting at http://localhost:$PORT - keep this window open, close it to stop."
(sleep 2; open "http://localhost:$PORT") &
python3 server.py
echo
read -r -p "The studio stopped. Press Enter to close."

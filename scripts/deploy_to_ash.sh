#!/usr/bin/env bash
#  Deploy current main → ash. Replaces the per-file scp pattern.
#
#  Steps:
#    1. git push (so ash can fetch).
#    2. On ash: git fetch + autostash-rebase onto origin/main.
#    3. Restart the dashboard service.
#    4. Show the restart status.
#
#  Autostash protects locally-modified files on ash (e.g. tools/
#  box_definitions.json freshly saved by the inspector) — they get
#  re-applied after the pull. If a real conflict happens, the script
#  bails out so you can resolve manually.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if ! git diff --quiet HEAD 2>/dev/null; then
    echo "warning: uncommitted changes in working tree — push will skip them" >&2
fi

echo "==> git push"
git push

echo "==> remote: git pull --rebase --autostash + restart"
#  Tree is cole-owned so the dashboard service (User=cole) can write
#  manifests + move images. Git runs as cole too.
ssh ash 'set -e
cd /opt/pokemon-champions
sudo -u cole git fetch origin main
sudo -u cole git rebase --autostash origin/main
sudo systemctl restart pokemon-champions-dashboard
sleep 1
systemctl is-active pokemon-champions-dashboard'

echo "==> deploy complete"

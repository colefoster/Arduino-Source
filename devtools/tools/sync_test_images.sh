#!/bin/bash
# Sync test_images/ between Mac and ash, keeping frames + manifests in step.
#
# Usage:
#   tools/sync_test_images.sh ash-to-local   # pull from ash (default — accepts come ash->Mac)
#   tools/sync_test_images.sh local-to-ash   # push from Mac (manual label corrections)
#
# Why this exists:
#   Past drift was caused by syncing only manifest.json without pulling the
#   PNGs they reference, leaving the manifest pointing at missing files and
#   crashing the regression runner. This script always rsyncs frames + manifest
#   together so they can never get out of step.
#
# What's excluded:
#   - test_images/_inbox/  (runtime triage queue, not source-of-truth)
#   - test_images/_inbox_curation_*.json  (curation logs)
#   - .DS_Store, *.tmp

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOCAL_DIR="${REPO_ROOT}/devtools/test_images/"
ASH_DIR="ash:/opt/pokemon-champions/test_images/"

EXCLUDES=(
    --exclude='_inbox/'
    --exclude='_inbox_curation_*.json'
    --exclude='.DS_Store'
    --exclude='*.tmp'
)

DIRECTION="${1:-ash-to-local}"

case "$DIRECTION" in
    ash-to-local|pull)
        echo "Pulling test_images/ from ash to local…"
        rsync -av "${EXCLUDES[@]}" "${ASH_DIR}" "${LOCAL_DIR}"
        ;;
    local-to-ash|push)
        echo "Pushing test_images/ from local to ash…"
        rsync -av "${EXCLUDES[@]}" "${LOCAL_DIR}" "${ASH_DIR}"
        ;;
    *)
        echo "Usage: $0 {ash-to-local|local-to-ash}"
        echo "  ash-to-local  pull from ash (default; accepts flow this way)"
        echo "  local-to-ash  push to ash (manual label corrections)"
        exit 1
        ;;
esac

echo "Done. Verify no stale entries:"
echo "  python3 -c \"
import json
from pathlib import Path
total = 0
for mp in Path('${REPO_ROOT}/test_images').rglob('manifest.json'):
    m = json.loads(mp.read_text())
    if not isinstance(m, dict): continue
    miss = [fn for fn in m if isinstance(m[fn], dict) and not (mp.parent / fn).exists()]
    if miss: print(f'{mp}: {len(miss)} stale')
    total += len(miss)
print(f'TOTAL stale: {total}')
\""

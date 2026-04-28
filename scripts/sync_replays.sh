#!/bin/bash
# Sync spectated replays from ash to ColePC via this Mac
# Run via cron every 2 hours: 0 */2 * * * /Users/cole/Dev/pokemon-champions/scripts/sync_replays.sh

set -e

STAGING="/tmp/replay_sync"
ASH_DIR="ash:/opt/pokemon-champions/data/showdown_replays/spectated/gen9championsvgc2026regma/"
COLEPC_DIR="colepc:C:/Dev/pokemon-champions/data/showdown_replays/gen9championsvgc2026regma/"
LOG="/tmp/replay-sync.log"

echo "[$(date)] Starting replay sync" >> "$LOG"

# Pull new from ash
mkdir -p "$STAGING"
rsync -az --ignore-existing "$ASH_DIR" "$STAGING/" >> "$LOG" 2>&1

# Push new to ColePC (use tar+scp since rsync to Windows is unreliable)
# Get list of what ColePC has
ssh colepc 'dir /b C:\Dev\pokemon-champions\data\showdown_replays\gen9championsvgc2026regma\gen9*.json 2>NUL' > /tmp/colepc_files.txt 2>/dev/null

# Find delta
python3 -c "
from pathlib import Path
ash = {f.name for f in Path('$STAGING').glob('*.json')}
pc = set(Path('/tmp/colepc_files.txt').read_text().strip().split('\n'))
pc = {f.strip() for f in pc if f.strip()}
new = ash - pc
if not new:
    print('No new files')
    exit(0)
print(f'{len(new)} new files to sync')
with open('/tmp/sync_delta.txt', 'w') as f:
    for name in sorted(new):
        f.write(name + '\n')
" >> "$LOG" 2>&1

if [ -f /tmp/sync_delta.txt ] && [ -s /tmp/sync_delta.txt ]; then
    cd "$STAGING"
    COPYFILE_DISABLE=1 tar czf /tmp/sync_replays.tar.gz -T /tmp/sync_delta.txt
    scp -q /tmp/sync_replays.tar.gz "colepc:C:/Dev/pokemon-champions/sync_replays.tar.gz"
    ssh colepc "cd C:\Dev\pokemon-champions && tar xzf sync_replays.tar.gz -C data\showdown_replays\gen9championsvgc2026regma\ && del sync_replays.tar.gz"
    rm -f /tmp/sync_replays.tar.gz /tmp/sync_delta.txt
    echo "[$(date)] Sync pushed to ColePC" >> "$LOG"
fi

echo "[$(date)] Done" >> "$LOG"

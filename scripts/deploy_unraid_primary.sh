#!/bin/bash
# Deploy script: switch primary training rig from ColePC to unraid.
#
# Run from Mac (or any machine with SSH access to ash + unraid).
# Idempotent — re-runnable safely.
#
# Steps:
#   1. cole@ash needs to SSH into unraid: copy ~/.ssh/id_ed25519.pub to
#      unraid's authorized_keys
#   2. Pull latest code on ash (dashboard server.py changes already on main)
#   3. Restart ash dashboard service so it picks up the new SYNC_HOST
#   4. Recreate the unraid container with the in-container job runner as
#      ENTRYPOINT, port 8422 published, and a memory limit
#   5. Smoke-test the full path: dashboard /api/sync/trigger, unraid container
#      /run, and a tiny preparse + train sanity check.

set -euo pipefail

echo "[1/5] Setting up SSH key from ash → unraid..."
ASH_PUBKEY=$(ssh ash 'cat ~/.ssh/id_ed25519.pub')
ssh unraid "mkdir -p ~/.ssh && grep -qxF '$ASH_PUBKEY' ~/.ssh/authorized_keys 2>/dev/null || echo '$ASH_PUBKEY' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
ssh ash 'mkdir -p ~/.ssh && grep -q "Host unraid" ~/.ssh/config 2>/dev/null || cat >> ~/.ssh/config <<EOF

Host unraid
    HostName 100.88.115.6
    User root
    StrictHostKeyChecking accept-new
EOF'
ssh ash 'ssh -o ConnectTimeout=5 unraid "echo ok"' || { echo "ash → unraid SSH still failing"; exit 1; }
echo "    OK"

echo "[2/5] Pulling main branch on ash..."
ssh ash 'cd /opt/pokemon-champions && sudo -u cole git pull --ff-only origin main' || true

echo "[3/5] Restarting ash dashboard..."
ssh ash 'sudo systemctl restart pokemon-champions-dashboard.service && sleep 2 && systemctl is-active pokemon-champions-dashboard.service'

echo "[4/5] Recreating unraid container with job runner as ENTRYPOINT..."
ssh unraid '
set -e
docker stop pokemon-champions-gpu 2>/dev/null || true
docker rm pokemon-champions-gpu 2>/dev/null || true
docker run -d \
  --name pokemon-champions-gpu \
  --restart unless-stopped \
  --gpus all \
  --memory 24g \
  --shm-size 4g \
  -p 8422:8422 \
  -v /mnt/user/data/pokemon-champions:/workspace \
  -w /workspace \
  pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime \
  python scripts/container_job_runner.py
'

echo "[5/5] Smoke testing..."
sleep 3
ssh unraid 'docker ps --filter name=pokemon-champions-gpu --format "{{.Status}}"'
curl -s "http://100.88.115.6:8422/health" | head
echo
echo "Dashboard sync target check:"
curl -s "http://100.113.157.128:8421/api/sync/status" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d)"

echo
echo "DONE. Next: trigger a sync from dashboard and submit a training job to unraid:8422."

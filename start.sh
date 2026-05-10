#!/bin/bash
# Bring up the full Pulse v2 stack for local development.
# Starts: k3s (if not running), Flask backend, monitoring (Prometheus/Grafana/Loki/Promtail).

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PULSE_DB="${PULSE_DB_PATH:-/tmp/pulse_smoke.db}"

cd "$REPO_ROOT"

echo "→ Checking k3s..."
if ! sudo systemctl is-active --quiet k3s; then
    echo "  Starting k3s..."
    sudo systemctl start k3s
    sleep 5
fi
kubectl get nodes >/dev/null && echo "  k3s OK"

echo "→ Ensuring UFW rule for port 5000..."
sudo ufw allow 5000/tcp >/dev/null 2>&1 || true

echo "→ Starting monitoring stack (Prometheus, Grafana, Loki, Promtail)..."
cd "$REPO_ROOT/monitoring"
sudo docker compose up -d
cd "$REPO_ROOT"

echo "→ Starting Flask backend in background..."
cd "$REPO_ROOT/portal/backend"
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
    source "$REPO_ROOT/.venv/bin/activate"
fi
# Kill any existing Flask on port 5000
existing_pid=$(sudo ss -tlnp 2>/dev/null | grep ":5000 " | grep -oP 'pid=\K[0-9]+' | head -1 || true)
if [ -n "$existing_pid" ]; then
    echo "  Killing existing Flask process (pid $existing_pid)..."
    kill "$existing_pid" 2>/dev/null || true
    sleep 1
fi
PULSE_DB_PATH="$PULSE_DB" nohup python3 app.py > /tmp/pulse-backend.log 2>&1 &
FLASK_PID=$!
echo "  Flask started (pid $FLASK_PID), logs at /tmp/pulse-backend.log"
cd "$REPO_ROOT"

echo "→ Waiting for backend to be ready..."
for i in {1..15}; do
    if curl -sf http://localhost:5000/health >/dev/null 2>&1; then
        echo "  Backend OK"
        break
    fi
    sleep 1
done

VM_IP=$(ip addr show eth0 2>/dev/null | grep -oP 'inet \K[0-9.]+' | head -1)
echo ""
echo "✓ Stack is up:"
echo "  Dashboard:  http://${VM_IP:-localhost}:5000/dashboard"
echo "  Grafana:    http://${VM_IP:-localhost}:3000   (admin/admin)"
echo "  Prometheus: http://${VM_IP:-localhost}:9090"
echo ""
echo "To stop:   ./stop.sh"
echo "Backend logs: tail -f /tmp/pulse-backend.log"
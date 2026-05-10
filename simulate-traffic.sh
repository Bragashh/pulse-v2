#!/bin/bash
# Continuously hit Pulse endpoints to generate metrics and logs.
# Run alongside the stack to see live data in Grafana.
#
# Usage: ./simulate-traffic.sh
# Stop:  Ctrl+C

BASE_URL="${BASE_URL:-http://localhost:5000}"

# Verify backend is up before starting
if ! curl -sf "$BASE_URL/health" >/dev/null 2>&1; then
    echo "✗ Backend not reachable at $BASE_URL"
    echo "  Start the stack with ./start.sh first."
    exit 1
fi

echo "→ Pumping traffic to $BASE_URL"
echo "  Endpoints: /health, /metrics, /uptime, /services, /score, /dora"
echo "  Press Ctrl+C to stop."
echo ""

trap 'echo ""; echo "✓ Stopped. Total requests: $count"; exit 0' INT

count=0
while true; do
    # Quick endpoints — hit each one. || true so a failed curl doesn't kill the loop.
    curl -sf "$BASE_URL/health"   >/dev/null 2>&1 && count=$((count + 1)) || true
    curl -sf "$BASE_URL/metrics"  >/dev/null 2>&1 && count=$((count + 1)) || true
    curl -sf "$BASE_URL/services" >/dev/null 2>&1 && count=$((count + 1)) || true
    curl -sf "$BASE_URL/score"    >/dev/null 2>&1 && count=$((count + 1)) || true

    # Slower endpoints — every N iterations to avoid hammering external sites
    if (( count % 20 == 0 )); then
        curl -sf "$BASE_URL/uptime" >/dev/null 2>&1 && count=$((count + 1)) || true
    fi
    if (( count % 40 == 0 )); then
        curl -sf "$BASE_URL/dora" >/dev/null 2>&1 && count=$((count + 1)) || true
    fi

    # Live counter
    printf "\r  Requests sent: %d" "$count"

    sleep 1
done
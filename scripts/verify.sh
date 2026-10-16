#!/usr/bin/env bash
# Usage: scripts/verify.sh [doctor] [--update-shots]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
API_PORT="${PLAYMAKERS_API_PORT:-8000}"
WEB_PORT="${PLAYMAKERS_WEB_PORT:-5173}"
API="http://127.0.0.1:$API_PORT"
WEB="http://127.0.0.1:$WEB_PORT"

doctor() {
  local ok=0
  curl -fsS "$API/healthz" >/dev/null 2>&1 && echo "api: up at $API" || { echo "api: down at $API"; ok=1; }
  curl -fsS "$WEB/" 2>/dev/null | grep -q "Playmakers" && echo "web: up at $WEB" || { echo "web: down at $WEB"; ok=1; }
  [ -x web/node_modules/.bin/vite ] && echo "web deps: installed" || { echo "web deps: missing (cd web && npm ci)"; ok=1; }
  python -c "import replay_api" 2>/dev/null && echo "python packages: installed" || { echo "python packages: missing (see README Quickstart)"; ok=1; }
  return $ok
}

port_busy() { curl -s -o /dev/null "http://127.0.0.1:$1/"; }

[ -f .venv/bin/activate ] && source .venv/bin/activate
set -m
if [ "${1:-}" = "doctor" ]; then doctor; exit $?; fi

UPDATE=0; [ "${1:-}" = "--update-shots" ] && UPDATE=1
for port in "$API_PORT" "$WEB_PORT"; do
  if port_busy "$port"; then echo "port $port is already serving; stop it or set PLAYMAKERS_API_PORT/PLAYMAKERS_WEB_PORT" >&2; exit 2; fi
done

RUN="$ROOT/artifacts/verify/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN"
CORS_ORIGINS="http://localhost:$WEB_PORT" uvicorn replay_api.main:app --host 127.0.0.1 --port "$API_PORT" >"$RUN/api.log" 2>&1 &
API_PID=$!
VITE_API_BASE="http://localhost:$API_PORT" npm run dev --prefix web -- --port "$WEB_PORT" --strictPort >"$RUN/web.log" 2>&1 &
WEB_PID=$!
cleanup() { kill -- -"$API_PID" -"$WEB_PID" 2>/dev/null || true; }
trap cleanup EXIT

for _ in $(seq 1 60); do
  curl -fsS "$API/healthz" >/dev/null 2>&1 && curl -fsS "$WEB/" >/dev/null 2>&1 && break
  sleep 1
done
doctor >"$RUN/doctor.txt" || { cat "$RUN/doctor.txt"; echo "not ready; logs in $RUN" >&2; exit 1; }

if [ "$UPDATE" = 1 ]; then
  PLAYMAKERS_WEB_URL="http://localhost:$WEB_PORT" npm run -s screenshot --prefix web 2>&1 | tee "$RUN/journey.txt"
else
  PLAYMAKERS_WEB_URL="http://localhost:$WEB_PORT" PLAYMAKERS_SHOTS_DIR="$RUN" npm run -s screenshot --prefix web 2>&1 | tee "$RUN/journey.txt"
fi
echo "PASS. Evidence in ${RUN#"$ROOT"/}"

#!/bin/bash
# Starts FastAPI on internal port 8000, then Flask (gunicorn) on public port 7860.
set -e

echo "[entrypoint] starting FastAPI on internal port 8000..."
uvicorn src.api:app --host 127.0.0.1 --port 8000 &
FASTAPI_PID=$!

echo "[entrypoint] waiting for FastAPI to be ready..."
for i in {1..45}; do
  if curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1; then
    echo "[entrypoint] FastAPI ready (after ${i}s)"
    break
  fi
  sleep 1
done

if ! curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1; then
  echo "[entrypoint] ERROR: FastAPI did not start within 45s"
  exit 1
fi

export API_BASE=http://127.0.0.1:8000
echo "[entrypoint] starting Flask (gunicorn) on public port 7860..."
exec gunicorn src.web:app \
  --bind 0.0.0.0:7860 \
  --workers 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -

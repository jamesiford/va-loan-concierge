#!/bin/bash
# ---------------------------------------------------------------------------
# predeploy hook — runs before `azd deploy`
# ---------------------------------------------------------------------------
# Builds the React frontend and copies the output to ./static/ so it is
# included in the App Service deployment package. FastAPI serves these files
# via a StaticFiles mount.
# ---------------------------------------------------------------------------

set -euo pipefail

echo "=== predeploy: Building React frontend ==="

# ── Build the React app ────────────────────────────────────────────────────

cd ui
npm ci --prefer-offline
npm run build
cd ..

echo "  React build complete (ui/dist/)"

# ── Copy build output to static/ for App Service ──────────────────────────

rm -rf static
mkdir -p static
cp -r ui/dist/* static/

echo "  Copied to ./static/ — will be included in deployment package"
echo "=== predeploy complete ==="

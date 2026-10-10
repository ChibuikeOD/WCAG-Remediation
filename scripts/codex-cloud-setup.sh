#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

run_as_root=()
if [[ "$(id -u)" -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    run_as_root=(sudo)
  else
    echo "This setup needs root access to install Linux system packages." >&2
    exit 1
  fi
fi

if command -v apt-get >/dev/null 2>&1; then
  "${run_as_root[@]}" apt-get update
  DEBIAN_FRONTEND=noninteractive "${run_as_root[@]}" apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    default-jre-headless \
    libqpdf-dev \
    qpdf \
    tesseract-ocr \
    tesseract-ocr-eng
fi

if command -v uv >/dev/null 2>&1; then
  (
    cd backend
    uv sync --frozen
    uv run playwright install --with-deps chromium
  )
else
  python -m pip install --upgrade pip
  python -m pip install -r backend/requirements.txt
  python -m playwright install --with-deps chromium
fi

npm ci --prefix frontend

if [[ -f pdfua_remediator_cpp/CMakeLists.txt ]]; then
  cmake -S pdfua_remediator_cpp -B pdfua_remediator_cpp/build
  cmake --build pdfua_remediator_cpp/build --config Release --parallel
fi

mkdir -p uploads output .artifacts

echo "PDFAccess cloud environment setup complete."

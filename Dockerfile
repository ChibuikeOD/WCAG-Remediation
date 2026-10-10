# ==========================================
# Production Dockerfile for WCAG Platform
# ==========================================
# Use official Playwright Python base image which contains pre-installed browsers and dependencies
FROM python:3.12.11-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV UPLOAD_DIR=/app/uploads
ENV OUTPUT_DIR=/app/output
# OpenDataLoader (Java) parses the full PDF page tree in memory. 128m starves
# it and triggers OutOfMemoryError on real documents, which surfaces as failed
# text extraction / untagged (inaccessible) output. 512m is a safe default for
# Docker/Compose; on a memory-constrained host lower this via the env var.
ENV _JAVA_OPTIONS="-Xmx512m"
# PyMuPDF/MuPDF expects the path to the tessdata folder ITSELF (not its parent),
# otherwise pix.pdfocr_tobytes() cannot find eng.traineddata and OCR silently fails.
ENV TESSDATA_PREFIX="/usr/share/tesseract-ocr/5/tessdata"
ENV PATH="/app/backend/.venv/bin:$PATH"
ENV DATABASE_URL="sqlite:////app/uploads/wcag_platform.db"
ENV PLAYWRIGHT_BROWSERS_PATH="/opt/playwright"

# Create app directory
WORKDIR /app

# Install Java JRE, build tools, QPDF dependencies, and Tesseract OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    cmake \
    build-essential \
    libqpdf-dev \
    qpdf \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Verify Java is available
RUN java -version

# Verify Tesseract + English language data are present where PyMuPDF expects them.
# Fail the build early if the tessdata path drifts in a future base image.
RUN tesseract --version && \
    test -f "$TESSDATA_PREFIX/eng.traineddata" \
    || (echo "ERROR: eng.traineddata not found at $TESSDATA_PREFIX" && \
        find /usr -name 'eng.traineddata' 2>/dev/null; exit 1)

# Verify qpdf CLI is available for post-repair structural validation.
RUN qpdf --version

# Copy requirements file first to cache package dependencies
COPY backend/pyproject.toml backend/uv.lock /app/backend/

# Install Python requirements
RUN pip install --no-cache-dir uv==0.11.18 && \
    uv sync --frozen --project backend --no-cache && \
    /app/backend/.venv/bin/python -m playwright install --with-deps chromium

# Create uploads and output directories
RUN useradd --uid 10001 --create-home app && \
    mkdir -p /app/uploads /app/output /app/.artifacts && \
    chown -R app:app /app/uploads /app/output /app/.artifacts

# Copy and build C++ pdfua-remediator-cli for Linux (cached layer)
COPY pdfua_remediator_cpp/CMakeLists.txt /app/pdfua_remediator_cpp/CMakeLists.txt
COPY pdfua_remediator_cpp/src /app/pdfua_remediator_cpp/src
RUN cmake -S /app/pdfua_remediator_cpp -B /app/pdfua_remediator_cpp/build && \
    cmake --build /app/pdfua_remediator_cpp/build --config Release

# Copy the entire project code into the container (non-C++ updates won't trigger recompilation)
COPY backend /app/backend
COPY rules /app/rules

USER app

# Expose port
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5)"

# Start FastAPI server using Uvicorn
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port $PORT"]

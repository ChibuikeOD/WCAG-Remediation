# ==========================================
# Production Dockerfile for WCAG Platform
# ==========================================
# Use official Playwright Python base image which contains pre-installed browsers and dependencies
FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV UPLOAD_DIR=/app/uploads
ENV OUTPUT_DIR=/app/output
ENV _JAVA_OPTIONS="-Xmx128m"
# PyMuPDF/MuPDF expects the path to the tessdata folder ITSELF (not its parent),
# otherwise pix.pdfocr_tobytes() cannot find eng.traineddata and OCR silently fails.
ENV TESSDATA_PREFIX="/usr/share/tesseract-ocr/4.00/tessdata"

# Create app directory
WORKDIR /app

# Install Java JRE, build tools, QPDF dependencies, and Tesseract OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    cmake \
    build-essential \
    libqpdf-dev \
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

# Copy requirements file first to cache package dependencies
COPY backend/requirements.txt /app/backend/requirements.txt

# Install Python requirements
RUN pip install --no-cache-dir -r backend/requirements.txt

# Create uploads and output directories
RUN mkdir -p /app/uploads /app/output && \
    chmod 777 /app/uploads /app/output

# Copy and build C++ pdfua-remediator-cli for Linux (cached layer)
COPY pdfua_remediator_cpp /app/pdfua_remediator_cpp
RUN cmake -S /app/pdfua_remediator_cpp -B /app/pdfua_remediator_cpp/build && \
    cmake --build /app/pdfua_remediator_cpp/build --config Release

# Copy the entire project code into the container (non-C++ updates won't trigger recompilation)
COPY . /app

# Expose port
EXPOSE 8000

# Start FastAPI server using Uvicorn
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port $PORT"]

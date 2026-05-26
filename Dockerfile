# ==========================================
# Production Dockerfile for WCAG Platform
# ==========================================
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV UPLOAD_DIR=/app/uploads
ENV OUTPUT_DIR=/app/output
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Create app directory
WORKDIR /app

# Install system dependencies (Java JRE, curl, and libs required for Chromium)
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    curl \
    ca-certificates \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Verify Java installation
RUN java -version

# Copy only requirements to leverage Docker build cache
COPY backend/requirements.txt /app/backend/requirements.txt

# Install python dependencies
RUN pip install --no-cache-dir -r backend/requirements.txt

# Install Playwright and download headless Chromium with its system dependencies
RUN pip install --no-cache-dir playwright && \
    playwright install --with-deps chromium

# Create uploads and output directories
RUN mkdir -p /app/uploads /app/output && \
    chmod 777 /app/uploads /app/output

# Copy the entire project code into the container
COPY . /app

# Expose the API port
EXPOSE 8000

# Start FastAPI server using Uvicorn
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

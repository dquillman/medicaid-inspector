FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for DuckDB and scikit-learn
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./

# Cloud Run uses PORT env var (default 8080)
ENV PORT=8080

# Run as non-root user for container hardening
RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

# Run uvicorn
CMD exec uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1 --timeout-keep-alive 30

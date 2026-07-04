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

# Container-level health signal for non-Cloud-Run runtimes (local docker run,
# docker-compose, CI smoke tests). Uses python (curl isn't in python:slim).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8080')+'/health').status==200 else 1)"

# Run as non-root user for container hardening
# --create-home is required so DuckDB can install httpfs extension (~/.duckdb)
RUN useradd --create-home --shell /bin/false appuser \
    && chown -R appuser:appuser /app
USER appuser

# Run uvicorn
CMD exec uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1 --timeout-keep-alive 30

FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Run as non-root user
RUN useradd -m -u 1000 -g users costoperator && chown -R costoperator:users /app
USER costoperator

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')" || exit 1

# Run operator
CMD ["kopf", "run", "--standalone", "--liveness=http://0.0.0.0:8080/healthz", "src/main.py"]

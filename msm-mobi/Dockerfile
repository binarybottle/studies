# Runtime for the MSM-MoBI scenario-conversation study site.
#
# The Python version and package versions are pinned so a study can be rebuilt
# years later exactly as participants experienced it.
#
# Build and run via compose.yml in the parent directory; this image is not
# meant to be run standalone.

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies before source, so editing application code does not invalidate
# the dependency layer. LiteLLM is the slow one (~1 minute on the droplet).
COPY requirements.txt .
RUN chmod 0644 requirements.txt \
    && pip install --no-cache-dir --requirement requirements.txt

COPY app ./app
COPY content ./content
# The pre-flight and export scripts run inside the container too.
COPY scripts ./scripts

# The database lives on a mounted volume, never in the image. STUDY_DB_PATH is
# set in compose.yml to point inside that volume.
RUN useradd --create-home --uid 10001 app \
    && chmod -R a+rX /app \
    && chown -R app:app /app \
    && mkdir -p /data \
    && chown app:app /data
USER app

EXPOSE 8000

# One worker. Every handler is asynchronous, so a worker holds hundreds of
# participants waiting on the model at once; a second worker would only buy
# CPU, which this app does not use, and would need the per-participant lock
# moved out of process memory. --proxy-headers makes uvicorn read the client
# address from Caddy's X-Forwarded-For; trusting it from any peer is safe only
# because the container publishes no port and Caddy is the sole route in.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]

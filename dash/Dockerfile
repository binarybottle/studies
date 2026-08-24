# Runtime for the DASH text screener study site.
#
# The Python version and package versions are pinned so a study can be rebuilt
# years later exactly as participants experienced it. That reproducibility is
# the main reason to containerize a short-lived research application at all.
#
# Build and run via compose.yml in the parent directory; this image is not
# meant to be run standalone.

FROM python:3.12-slim-bookworm

# Unbuffered output so uvicorn logs appear immediately in `docker compose logs`.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies are installed before the source is copied so that editing
# application code does not invalidate the dependency layer on rebuild.
#
# The chmod matters: COPY preserves file modes from the build context, and
# scp preserves them from the source machine, so a file that was 0600 on a
# laptop arrives 0600 here and is unreadable once the image drops to the
# unprivileged user below.
COPY requirements.txt .
RUN chmod 0644 requirements.txt \
    && pip install --no-cache-dir --requirement requirements.txt

COPY study_site.py store.py ./

# The database lives on a mounted volume, never in the image. STUDY_DB_PATH is
# set in compose.yml to point inside that volume.
RUN useradd --create-home --uid 10001 app \
    && chmod 0644 /app/*.py \
    && chown -R app:app /app \
    && mkdir -p /data \
    && chown app:app /data
USER app

EXPOSE 8000

# One worker: SQLite with a single writer is the intended deployment shape.
# Scaling past this means moving store.py to Postgres first.
#
# --proxy-headers makes uvicorn read the client address from the
# X-Forwarded-For header Caddy sets, instead of reporting Caddy's own
# container address for every request. Without it the per-address rate limit
# on /api/opt-in sees one caller for the whole study and starts refusing real
# participants. Trusting the header from any peer is safe here only because
# the container publishes no port: Caddy is the sole route in.
CMD ["uvicorn", "study_site:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]

# CloudOps AI API. Production runs on Vercel's Python runtime; this image is
# for local development, CI and anyone who wants to self-host.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt "uvicorn[standard]>=0.30,<1"

COPY . .

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 cloudops && chown -R cloudops /app
USER cloudops

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2).status == 200 else 1)"

# Apply migrations when a database is configured, then serve.
CMD ["sh", "-c", "if [ -n \"$DATABASE_URL\" ]; then python -m alembic upgrade head; fi && exec python -m uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]

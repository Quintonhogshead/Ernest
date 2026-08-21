# Ernest dashboard — container image for Fly.io (or any host).
FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code.
COPY ernest/ ./ernest/
COPY jobs/ ./jobs/
COPY dashboard/ ./dashboard/
COPY scripts/ ./scripts/

# Persist keys + library on a mounted volume (see fly.toml).
ENV ERNEST_ENV_PATH=/data/.env \
    ERNEST_DB_PATH=/data/ernest.db \
    PORT=8080

EXPOSE 8080

# --host 0.0.0.0 requires ERNEST_DASHBOARD_PASSWORD (the app fails closed otherwise).
CMD ["python", "-m", "dashboard.app", "--host", "0.0.0.0", "--port", "8080"]

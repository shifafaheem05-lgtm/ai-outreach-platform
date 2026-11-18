# Stage 1: build the React frontend
FROM node:22-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: FastAPI serving API + built frontend on one port
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 FRONTEND_DIST=/app/frontend_dist APP_ENV=production
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /fe/dist /app/frontend_dist
RUN useradd --system --no-create-home app && chown -R app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/api/health'%os.environ.get('PORT','8000'),timeout=4)"
# Run exactly ONE process: the e-mail scheduler runs inside it. Behind a reverse proxy set FORWARDED_ALLOW_IPS to the proxy's address.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]

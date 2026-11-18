# Stage 1: build the React frontend
FROM node:20-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: FastAPI serving API + built frontend on one port
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 FRONTEND_DIST=/app/frontend_dist
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /fe/dist /app/frontend_dist
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

# Cisco PO Status Tracker - single-container build for Render (same pattern as the BSPL app).
# Stage 1 builds the React frontend; stage 2 is the Python runtime that serves the API and the built UI.

FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=frontend-build /app/frontend/dist frontend/dist
WORKDIR /app/backend

# One worker on purpose: fetch jobs, sync progress and the result cache live in memory, so every request
# must reach the same process. Threads give the concurrency. Render sets $PORT at boot.
EXPOSE 8000
CMD ["sh", "-c", "gunicorn -w 1 --threads 8 --timeout 300 -b 0.0.0.0:${PORT:-8000} app:app"]

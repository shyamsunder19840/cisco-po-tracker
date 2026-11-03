# Cisco PO Status Tracker

Flask backend + React (Vite) frontend, built from `Cisco_PO_Tracker_API_Reference.pdf`.

## Run (single port: 5000)
Flask serves both the API and the built React app.
```
cd frontend && npm install && npm run build   # only after frontend changes
cd ../backend && .venv\Scripts\python app.py
```
Open http://localhost:5000

On Linux: `gunicorn -w 1 --threads 8 -b 0.0.0.0:5000 app:app` from `backend/`.

(Optional) For live-reload UI development, `npm run dev` in `frontend/` serves on :5173 and proxies `/api` to :5000. Don't run it for normal use.

## Config
All credentials/URLs live in `backend/.env` (git-ignored). Never commit it.

## Endpoints
POST `/api/submit` · POST `/api/submit_by_date` · GET `/api/progress/<job>` · POST `/api/download`

## Deploying to Render
Same pattern as the BSPL app: `Dockerfile` + `render.yaml` (free plan, manual deploy).
1. Create an empty GitHub repo (e.g. `cisco-po-tracker`) and push this folder to it (`backend/.env` is git-ignored).
2. On Render: New > Blueprint > pick the repo. Fill in the `sync: false` variables (paste `backend/.env` via "Add from .env").
3. Limits of the free plan: no persistent disk, so the Daily tracker history and any change made in the app's Settings reset on every redeploy/restart, and the service sleeps when idle. Values from Render's environment are re-applied on each boot.
4. The app has no login. Anyone with the URL can use it, including "Sync into Business Central".

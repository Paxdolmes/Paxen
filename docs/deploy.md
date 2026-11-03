# Deploying Paxen

Three pieces, all from this repo:

| Piece | What it does | Where |
|---|---|---|
| **API** | serves the app (`backend/`, Dockerfile default command) | Railway service #1 |
| **Worker** | records live TfL data 24/7, sends alerts, retrains the model (`python -m paxen.worker`) | Railway service #2, same code |
| **Database** | PostgreSQL, shared by API and worker | Railway Postgres |
| **Web app** | the Next.js app (`web/`) | Vercel |

Tested locally against PostgreSQL 16 with the API and worker as separate processes.

## 1. Railway (backend + database), ~10 min

1. Sign in at **https://railway.com** with GitHub.
2. **New Project → Deploy from GitHub repo → `Paxdolmes/Paxen`**.
3. Open the new service → **Settings**:
   - **Source → Root directory:** `backend`
   - **Source → Branch:** `claude/happy-shannon-mkx82r` (or `main` once merged)
   - Railway detects the `Dockerfile` automatically.
   - **Networking → Generate domain.** This is your API URL, e.g. `https://paxen-api-production.up.railway.app`.
   - Rename the service to `api`.
4. In the project, **+ Create → Database → PostgreSQL**.
5. `api` service → **Variables** → add:
   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   PAXEN_PROVIDER=tfl
   TFL_APP_KEY=<your TfL primary key>
   PAXEN_RUN_WORKERS=0
   ```
6. Create the worker: **+ Create → GitHub repo → `Paxdolmes/Paxen`** again, then:
   - **Root directory:** `backend`, same branch
   - **Settings → Deploy → Custom start command:** `python -m paxen.worker`
   - No domain needed. Rename it to `worker`.
   - **Variables:** the same four as above.
7. Check it: open `https://<your-api-domain>/v1/health`. You should see `"provider":"tfl"`, and after a minute `"fresh":true`.

## 2. Vercel (web app), ~5 min

1. **https://vercel.com/new → Import `Paxdolmes/Paxen`.**
2. **Root directory:** `web` (the framework is detected as Next.js).
3. **Environment variables:** `NEXT_PUBLIC_PAXEN_API_URL` = your Railway API URL, with no trailing slash.
4. **Deploy.** Open the URL on your phone → Share → **Add to Home Screen**.
5. Optional: lock the API to your web domain by setting `PAXEN_CORS_ORIGINS=https://<your-app>.vercel.app` on both Railway services.

## Running the same layout locally

```bash
export DATABASE_URL=postgres://localhost/paxen PAXEN_PROVIDER=tfl TFL_APP_KEY=...
PAXEN_RUN_WORKERS=0 uvicorn paxen.main:app --port 8000   # API
python -m paxen.worker                                    # worker, in another terminal
```

The test suite also runs against Postgres:
`PAXEN_TEST_DATABASE_URL=postgresql://postgres@localhost/paxen pytest -q`

## Costs (rough)
Railway charges by usage. API + worker + a small Postgres for a pilot typically costs a few dollars a month. Vercel's
hobby tier covers the web app. TfL's API is free (500 requests/min with your key).

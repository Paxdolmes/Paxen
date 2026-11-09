# Deploying Paxen, step by step

| Piece | What it does | Where |
|---|---|---|
| **API** | serves the app (`backend/`, Dockerfile default command) | Railway service `api` |
| **Worker** | records every Tube, Overground, Elizabeth line, DLR and tram prediction (every 30 s) and the whole bus network (every 2 min, archive only); infers arrivals, sends alerts, retrains (`python -m paxen.worker`) | Railway service `worker`, same code |
| **Database** | PostgreSQL: users, trips, alerts, sampled predictions, arrivals | Railway Postgres |
| **Raw archive** | every TfL response, gzip-compressed, so history can always be rebuilt | Cloudflare R2 bucket |
| **Web app** | the Next.js app (`web/`) | Vercel |

Total time: about 30 minutes. Tested locally on PostgreSQL 16 with live TfL data.

---

## Step 1: Cloudflare R2 for the raw archive (~10 min)

1. Sign up or log in at **https://dash.cloudflare.com/sign-up**.
2. In the left menu open **R2 Object Storage**. If asked, add a payment method. The free tier covers 10 GB;
   Paxen adds about **7 GB a day** compressed (rail ~1 GB + buses ~6 GB), about $3 a month for each month of history.
3. Click **Create bucket** and name it `paxen-raw`. Location: **Automatic** (or a European jurisdiction hint).
4. Back on the R2 page, click **Manage R2 API Tokens** (or **API → Manage API tokens**) → **Create API token**:
   - Permissions: **Object Read & Write**
   - Specify bucket: **paxen-raw**
   - Click **Create**.
5. Copy these three values from the page shown (they're only shown once):
   - **Access Key ID**
   - **Secret Access Key**
   - **Endpoint for S3 clients**: `https://<account-id>.r2.cloudflarestorage.com`

## Step 2: Railway project and database (~5 min)

1. Sign in at **https://railway.com** with GitHub.
2. **New Project → Deploy from GitHub repo → `Paxdolmes/Paxen`**. This creates the first service.
3. Open the service → **Settings**:
   - **Source → Root directory:** `backend`
   - **Source → Branch:** `claude/happy-shannon-mkx82r` (or `main` once merged)
   - **Deploy → Region:** **EU West (Amsterdam)**. Users' places and trips are personal data, so keep them in the EU.
   - **Networking → Generate domain.** Note the URL, e.g. `https://paxen-api-production.up.railway.app`.
   - Rename the service `api`.
4. In the project: **+ Create → Database → PostgreSQL**. Set its region to **EU West** too.

## Step 3: Variables for the `api` service (~3 min)

`api` → **Variables → Raw editor**, paste and fill in:

```
DATABASE_URL=${{Postgres.DATABASE_URL}}
PAXEN_PROVIDER=tfl
TFL_APP_KEY=<your TfL "paxen" primary key>
PAXEN_RUN_WORKERS=0
```

## Step 4: The `worker` service (~5 min)

1. In the project: **+ Create → GitHub repo → `Paxdolmes/Paxen`**.
2. **Settings:** Root directory `backend`, same branch, region **EU West**.
3. **Settings → Deploy → Custom start command:** `python -m paxen.worker`
4. No domain needed. Rename it `worker`.
5. **Variables → Raw editor:**
   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   PAXEN_PROVIDER=tfl
   TFL_APP_KEY=<your TfL "paxen" primary key>
   PAXEN_POLL_INTERVAL=30
   PAXEN_RECORD_MODES=tube,overground,elizabeth-line,tram
   PAXEN_PREDICTION_RETENTION_DAYS=14
   PAXEN_ARCHIVE_URL=s3://paxen-raw/london
   AWS_ACCESS_KEY_ID=<R2 Access Key ID>
   AWS_SECRET_ACCESS_KEY=<R2 Secret Access Key>
   AWS_ENDPOINT_URL=<R2 endpoint for S3 clients>
   AWS_REGION=auto
   ```

   Leaving out `PAXEN_ARCHIVE_ONLY_MODES` leaves out the network-wide bus archive (~$12/month extra, and not usable for
   training until BODS is connected). To add it later: `PAXEN_ARCHIVE_ONLY_MODES=bus` and
   `PAXEN_ARCHIVE_ONLY_INTERVAL=120`.

## Step 5: Check the backend (~2 min)

1. Open `https://<your-api-domain>/v1/health`. You should see `"provider":"tfl"`, and within a minute `"fresh":true`.
2. Refresh after a few minutes: `predictions_recorded` and `observed_arrivals` should keep rising.
3. `worker` → **Logs**: look for lines like
   `recorder: {'network': [{'mode': 'tube', 'seen': 3560, 'kept': 520, 'archived': True}, …]` every 30 s, and
   `archive: [{'mode': 'bus', 'mb': 95.1, 'archived': True}]` every 2 min. `archived: True` means R2 is working.
4. In Cloudflare → R2 → `paxen-raw`, files appear under `london/raw/tfl/<date>/<hour>/`.

## Step 6: The web app on Vercel (~5 min)

1. **https://vercel.com/new → Import `Paxdolmes/Paxen`.**
2. **Root directory:** `web`.
3. **Environment variables:** `NEXT_PUBLIC_PAXEN_API_URL` = your Railway API URL (no trailing slash).
4. **Deploy.** Open the URL on your phone → Share → **Add to Home Screen**.
5. Optional: on both Railway services set `PAXEN_CORS_ORIGINS=https://<your-app>.vercel.app`.

## Step 7: Leave it running

- **~1 day:** enough raw samples network-wide.
- **~2 weeks:** every weekday and time of day seen twice.
- **~3 weeks:** the real test, on a held-out week. The model switches itself on only if it beats TfL.
- **2–3 months:** disruption-specific patterns.

---

## What's stored where
| Data | Location | Retention |
|---|---|---|
| Users, places (~10 m precision), commutes, trips, alerts | Postgres | until the user deletes it |
| Rail/DLR/tram predictions: every snapshot in the last 2 min before arrival, one per lead-time group earlier (~15% of the feed) | Postgres | 60 days (`PAXEN_PREDICTION_RETENTION_DAYS`) |
| Bus predictions on users' routes (full detail) | Postgres | 60 days |
| Inferred arrivals (with bounds + quality) | Postgres | kept |
| Raw TfL responses for per-stop polls | Postgres | payload dropped after 14 days |
| Raw TfL responses for whole-network polls: rail every 30 s, all buses every 2 min | R2 (gzip) | kept; set an R2 lifecycle rule if you want expiry |

## Buses: what the archive is for
Network-wide bus predictions go to R2 only: too big for the database, and polling every 2 minutes is too coarse
to work out exact bus arrival times from countdowns. To learn from them, add the **Bus Open Data Service**
(free official GPS positions for every bus, https://data.bus-data.dft.gov.uk). Its positions give exact arrival
times to pair with the archived predictions. Buses on users' own routes are already recorded in full detail and
used by the model today.

## If something goes wrong
- **TfL rejects the key:** the logs show `TfL rejected TFL_APP_KEY`, and Paxen falls back to key-less access
  (50 requests/min, enough for the API but tight for the worker). Fix the variable.
- **R2 unreachable:** recording continues, the logs show `archive write failed`, and `archived: False`.
- **Rebuild arrivals after an inference change:** run `python -m paxen.reinfer` as a one-off on the worker.

## Running the same layout locally

```bash
export DATABASE_URL=postgres://localhost/paxen PAXEN_PROVIDER=tfl TFL_APP_KEY=...
PAXEN_RUN_WORKERS=0 uvicorn paxen.main:app --port 8000                      # API
PAXEN_ARCHIVE_URL=file:///tmp/paxen-archive python -m paxen.worker          # worker
```
Tests against Postgres: `PAXEN_TEST_DATABASE_URL=postgresql://postgres@localhost/paxen pytest -q`

## Costs (rough)
Measured on live data (3 Nov 2026):
- **Postgres** (measured 9 Nov 2026): about 1.8M prediction rows a day (~0.55 GB) and 380k arrivals a day
  (~0.1 GB). Predictions older than 3 days are thinned to the sample the model evaluation reads (about 1 in 17, see
  docs/model-evaluation.md), so a day of history costs ~0.13 GB once it's old. Rough size by retention
  (`PAXEN_PREDICTION_RETENTION_DAYS`, default 60): 60 days ~10 GB, 30 days ~6 GB, 14 days ~4 GB. `/v1/health` shows the
  live size (`data.db_mb`). Railway's Hobby plan caps a volume at 5 GB; Pro starts at 50 GB. Postgres reuses the space
  of deleted rows but doesn't hand it back to the disk, so the on-disk size never shrinks by itself.
- **R2:** about 7 GB/day (rail ~1 GB, buses ~6 GB), so about $3 a month for each month of history kept.
  Drop buses to every 5 min (`PAXEN_ARCHIVE_ONLY_INTERVAL=300`) to cut that by 60%.
- **Downloads:** the bus feed is ~95 MB per poll (~69 GB/day at 2 min). Railway doesn't charge for inbound traffic.
- Vercel's hobby tier covers the web app. The TfL API is free.

# Local operation without Supabase

PromiseFlow runs on one computer with FastAPI serving both the interface and API. SQLite stores data on that computer. No Supabase account or API key is required.

## First setup on Windows

Install Python 3.12 and Node.js 24. From the repository folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd --prefix frontend ci
npm.cmd run build
```

If `.env` does not exist, copy `.env.example` to `.env`. If switching an existing setup, preserve a private backup of `.env`, then update these values:

```dotenv
PROMISEFLOW_MODE=demo
PROMISEFLOW_DATABASE_URL=
PROMISEFLOW_DB=data/promiseflow.db
PROMISEFLOW_ORIGINS=http://127.0.0.1:8017,http://localhost:8017,http://127.0.0.1:5173,http://localhost:5173
```

Remove any inherited `PROMISEFLOW_DATABASE_URL` from the terminal environment as well: environment variables take precedence over `.env`. Supabase public keys and the PostgreSQL CA setting are not needed for SQLite.

## Start and sign in

```powershell
.\start.ps1
```

Open http://127.0.0.1:8017/ and use username `manager`, password `promise-demo`. Keep the server running while using the workspace. Stop with Ctrl+C and run the same command to restart. The server listens only on this computer.

The existing local database is reused. A fresh installation creates synthetic demo data; cloud data is not automatically downloaded. These shared demo credentials are for local evaluation, not production access.

## Data and verification

Data persists at `data/promiseflow.db`. Stop the application before copying the database and any accompanying `-wal`/`-shm` files for a backup. Do not commit databases, `.env`, or private configuration backups to GitHub; they are ignored.

Open http://127.0.0.1:8017/api/health to verify `status: ok` and `database: sqlite`.

This local configuration does not repair or update a Vercel deployment. SQLite requires a persistent writable disk; do not use a serverless temporary directory for real planning records.

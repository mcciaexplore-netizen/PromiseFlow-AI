# Vercel build configuration

## Startup database errors

`DatabaseUnavailable` while importing `backend/app.py` means the function could not open its configured database, not that a favicon is missing. Connection diagnostics now distinguish `DB_AUTH`, `DB_TLS`, `DB_DNS`, and `DB_NETWORK` without including driver text or credentials.

For the MCCIA deployment, verify these server environment settings and redeploy after saving:

- `PROMISEFLOW_DATABASE_URL`: the chosen Supabase project's **session pooler** PostgreSQL URI, including its correct database password and `sslmode=verify-full`. A public API key cannot substitute for this URI.
- `PROMISEFLOW_DB_SSLROOTCERT=backend/certs/supabase-ca.crt`. Relative certificate paths resolve against the application root. If this variable is absent, Supabase endpoints use the bundled CA automatically. An explicitly configured missing file is rejected, not silently ignored.
- `PROMISEFLOW_MODE=demo` for the previously migrated synthetic factory. Use a separate database/schema for production.
- `PROMISEFLOW_ORIGINS=https://promise-flow-ai.vercel.app` for the new MCCIA address.

Git pushes transfer source code, not the old Vercel project's environment variables. Do not upload `.env` to GitHub. A successful redeployment must be followed by a PostgreSQL `/api/health` response and an actual login check.

The repository-root `pyproject.toml` declares `backend.app:app` as the FastAPI entrypoint and builds the React frontend into `frontend/dist`. FastAPI serves the interface and `/api` on the same origin. Keep the Vercel Root Directory at the repository root and select the FastAPI framework. Remove stale Build Command or Output Directory overrides; dashboard build commands override the repository script.

This fixes entrypoint discovery, not every deployment/runtime requirement. Follow the [official FastAPI guide](https://vercel.com/docs/frameworks/backend/fastapi).

## Server configuration

Local `.env` files are deliberately not published. Configure the server-only `PROMISEFLOW_DATABASE_URL` in the deployment environment using the Supabase session pooler and `sslmode=verify-full`. The public Supabase API URL and publishable key cannot replace it. Configure a trusted CA certificate accessible inside the deployment if required; a Windows path in `PROMISEFLOW_DB_SSLROOTCERT` will not work on Vercel. Never disable TLS verification.

Set `PROMISEFLOW_MODE` to match the database. The migrated sample database is **demo**, not production. Production requires a separate database/schema, a unique `PROMISEFLOW_ADMIN_PASSWORD` of at least 16 characters and exact HTTPS `PROMISEFLOW_ORIGINS`. Keep a demo deployment access-protected because its credentials are published. Do not put database secrets in `NEXT_PUBLIC_` or `VITE_` variables.

## Runtime boundary

The current planner uses a single-process thread worker after returning a queued-job response, process-local locks/rate limits, and startup cleanup of unfinished jobs. Autoscaled or short-lived function instances do not satisfy that execution contract: jobs may be interrupted and one instance can mark another instance's work interrupted. Supabase persistence alone does not fix this. Do not treat a successful Vercel build or login as validation of scheduling on serverless functions.

For the complete application, deploy the existing Docker image on a persistent Python service with one API worker and Supabase storage. A Vercel frontend can proxy `/api` to that service once its HTTPS address is available. Supporting the full planner directly on Vercel requires a durable external worker and coordinated job ownership before production acceptance.

After deployment, verify `/api/health` reports PostgreSQL, login returns JSON, the saved active plan is present, and the supported worker can complete and publish a sandbox scenario. A frontend-only page is not a working backend deployment.

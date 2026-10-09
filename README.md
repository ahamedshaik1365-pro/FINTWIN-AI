# FinTwin AI

FinTwin AI is a personal finance workspace for early-career professionals in India. It includes a responsive, native HTML/CSS/JavaScript dashboard and a user-scoped FastAPI service. The supplied dashboard reference informed the dark navy and violet layout; the uploaded family portrait is used as the profile image. Dashboard figures are illustrative **Preview data** until real records are imported.

## Current implementation

- Responsive dashboard and navigable pages for finance modules, transactions, reports, settings, profile, and ML Studio.
- Interactive financial widgets, cash-flow and spending charts, INR formatting, transaction/goal entry, simulator, SIP calculator, salary explainer, and rule-based FinGuide.
- FastAPI service with password hashing, short-lived JWTs, login throttling, user-owned records, profile photo validation, and persistent SQLite local development (PostgreSQL via `DATABASE_URL`).
- CSV/XLSX dataset upload, schema and quality inspection, checksum storage, private dataset ownership, and supervised regression/classification training against dummy baselines. Models stay inactive until approval.
- The provided synthetic CSVs and data dictionary are included in `public/datasets/`; they can be inspected in the interface or used for a local training demonstration. The dataset notes state they are fictional and should not be treated as real population data.

Profile preferences, transactions, goals, monthly summaries, dataset uploads, and model training are saved to the API when signed in. The Bills & reminders page saves one-time and recurring bills, creates in-app reminders as due dates approach, and records paid bills as expenses. The Bank connections page starts a Setu Account Aggregator consent flow, checks consent status, retrieves approved transaction data, deduplicates imports, and allows consent revocation. Large training jobs use a persistent Celery/Redis queue when configured, with an in-process background fallback for local development. The Overview reflects saved profile and financial data. Calculators run locally using transparent formulas.

## One-click start

On Windows, double-click `Start-FinTwin.bat`. It starts the local API and website, applies database migrations, creates a random local API secret if needed, and opens the dashboard. First launch may install Python dependencies and needs an internet connection. Python 3.11+ and Node.js 20+ must be installed. The API and site listen only on this computer.

## Run the frontend

Requires Node.js 20+.

```powershell
npm run dev
```

The local frontend opens at `http://localhost:5173`. It uses native HTML, CSS, and JavaScript. Text sizes are enlarged for readability, and the dashboard assistant follows pointer movement with reduced-motion support.

## Run the API

Requires Python 3.11+.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set a unique random `JWT_SECRET` in `backend/.env` before starting the service. For local development only, SQLite is the default. Set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL for a PostgreSQL database.

```powershell
alembic upgrade head
uvicorn app.main:app --reload
```

The API docs are at `http://localhost:8000/docs`; health is available at `/health`.

## Create the initial account securely

```powershell
cd backend
python scripts/create_initial_user.py
```

The password is read through a hidden prompt, hashed with Argon2, and is never printed or placed in source. Do not commit `.env`, uploaded data, or generated model artifacts.

## Dataset workflow

Authenticate in ML Studio, then upload `.csv`, `.xlsx`, or `.xls` through the interface (or `POST /api/v1/datasets` with multipart field `file`). The response includes a schema preview, missing-value counts, duplicate count, and SHA-256 checksum. The data remains scoped to its owner. The supplied synthetic users dataset can be used as a demonstration; choose `risk_flag_12m` as the target and exclude identifiers and future-outcome columns from features. New models must be evaluated and explicitly approved before activation. Do not include personally identifying fields as model features.

As a wiring check only, the supplied synthetic risk-label dataset produced a random forest macro F1 of 0.732 and accuracy of 0.893 on its held-out split (75 rows), versus a dummy baseline accuracy of 0.773. These values describe a tiny synthetic dataset and do not indicate real-world financial risk performance.

## Bank data consent and bill reminders

Bill reminders are created in **Bills & reminders**. The daily scheduler in the deployment stack creates in-app notifications; local development also checks for due bills when the page or notification list is opened. Email/SMS delivery is not configured. Marking a recurring bill paid records the expense and advances its next due date.

Bank linking requires an eligible FIU deployment and Setu product credentials. Configure `SETU_BASE_URL`, `SETU_PRODUCT_INSTANCE_ID`, `SETU_ACCESS_TOKEN`, and `SETU_REDIRECT_URL` in `backend/.env` for local testing. Never store bank passwords or PINs in FinTwin. The user reviews and approves consent on the provider page. The sandbox will not connect real bank accounts; production credentials require provider onboarding and FIU approval. The adapter intentionally refuses to create a consent without the access token and product instance ID.

For datasets over 50,000 labelled rows, local mode runs training in a FastAPI background task. The production stack sends queued runs to Celery/Redis and schedules reminders with Celery Beat. The worker must share database, uploaded dataset, and model artifact storage with the API.

## Production deployment

The production stack uses Docker Compose, PostgreSQL, Redis/Celery, Caddy TLS, persistent uploads/models, and HttpOnly secure session cookies. It requires a public DNS name pointed at the server, Docker Compose, open ports 80/443, and a Setu FIU production configuration for live bank access.

```sh
cp .env.production.example .env.production
# Edit .env.production: set PUBLIC_DOMAIN, POSTGRES_PASSWORD, JWT_SECRET, and provider settings.
docker compose --env-file .env.production up -d --build
```

Keep `.env.production` private and back up PostgreSQL plus the `fintwin_uploads` and `fintwin_models` volumes. Production deployment has not been run from this development workspace; configure a real server/domain and credentials before publishing.

## Safety and limitations

Financial projections are educational illustrations, not guarantees or regulated advice. Bank data is imported only after provider consent; revoke consent from Bank connections. In local mode, large-data training falls back to an in-process task that will stop if the API process exits. Production uses the configured Redis queue. Local training supports datasets up to the 250,000-row upload limit, subject to the host's memory and CPU. Evaluation metrics are measured on a held-out split and do not guarantee future performance.

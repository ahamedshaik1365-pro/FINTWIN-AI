# FinTwin AI architecture

## Current data flow

The static, dependency-free browser client renders the dashboard and module pages. Interactive dashboard preview data is explicitly marked as illustrative. The FastAPI service provides the authenticated data and model APIs. Its default local database is SQLite; `DATABASE_URL` can select PostgreSQL.

```text
Browser UI → FastAPI routes → authenticated user scope → SQLAlchemy → SQLite/PostgreSQL
                                      └→ dataset validation → sklearn pipeline → private joblib artifact
```

## Security boundaries

- Registration hashes passwords with Argon2. Access tokens are short lived JWTs.
- Login attempts have a rate limit. Financial records and uploaded datasets are filtered by the authenticated owner ID.
- User uploads are size/format checked, stored under generated server-side names, and are not served as public static assets.
- Uploaded CSV headers and file names are escaped before rendering. Personally identifying feature columns and known future outcome labels are rejected by the trainer.
- New model artifacts are stored under the backend artifact directory and stay inactive until the account owner approves one. Prediction endpoints resolve artifacts only under that registry.
- Synthetic example data is served from `public/datasets`; it is fictional and must not be interpreted as a real customer dataset.

## Implemented API areas

Auth, profile, photo upload, transactions, dashboard summary/breakdown, goals, transparent baseline forecasts, scenario calculations, dataset inspection, supervised regression/classification evaluation, model activation, and prediction are implemented. Other feature modules currently include interactive UI and transparent preview/rule-based calculations while their specialized persistence and APIs are still incremental work.

## Database setup

The first Alembic migration creates users, transactions, goals, datasets, training runs, and model registry records. After setting `DATABASE_URL`, run `alembic upgrade head` from `backend/` before starting Uvicorn.

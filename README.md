# Task Dashboard

FastAPI + async SQLAlchemy + PostgreSQL.

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # then fill in DATABASE_URL and SECRET_KEY
uvicorn main:app --reload
```

For first-time development, set `SEED_DEMO_USERS=true` and `SEED_PASSWORD=<something>` in `.env`
to create Calven (admin), Mahymar and Sothearith. Leave it off in production and create users
via `POST /users` as an admin.

Put your existing stylesheet at `templates/styles/style.css`.

Interactive API docs: http://localhost:8000/docs (use the Authorize button to log in).

## Tests

```bash
pytest
```

Tests use a temporary SQLite database; no Postgres needed.

## Database note

Tables are now `users` and `tasks` (lowercase) and the password column is `hashed_password`.
`create_all` will not alter your old `"Users"`/`"Tasks"` tables, so for a dev database either
drop it and let the app recreate it, or write an Alembic migration if you have data to keep.

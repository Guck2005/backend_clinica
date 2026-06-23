# CaisseTrace Backend

FastAPI backend for Sprint 1 (catalogue).

## Local setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.scripts.import_catalogue_tex ..\catalogue.tex
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Default demo credentials:

- admin: `admin` / `1234`
- caissier: `amadou.k` / `1234`

Railway should provide `DATABASE_URL` for PostgreSQL.

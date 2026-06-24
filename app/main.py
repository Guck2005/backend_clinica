from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import alerts, auth, caisses, catalogue, factures, payments, transactions, users, versements, visits
from app.api.routes import audit_logs, backups, reports
from app.core.config import settings
from app.core.migrations import migrate_database
from app.core.workers import start_background_workers, stop_background_workers
from app.db.session import engine
from app.db.base import Base
from app.scripts.seed_demo_users import ensure_demo_users


app = FastAPI(title="CaisseTrace API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://yello-hack.vercel.app",
    ] + settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    migrate_database()
    Base.metadata.create_all(bind=engine)
    ensure_demo_users()
    start_background_workers()


@app.on_event("shutdown")
def on_shutdown() -> None:
    stop_background_workers()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(caisses.router)
app.include_router(catalogue.router)
app.include_router(alerts.router)
app.include_router(audit_logs.router)
app.include_router(backups.router)
app.include_router(factures.router)
app.include_router(payments.router)
app.include_router(reports.router)
app.include_router(transactions.router)
app.include_router(users.router)
app.include_router(versements.router)
app.include_router(visits.router)

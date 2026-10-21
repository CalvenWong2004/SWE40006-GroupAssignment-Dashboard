import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import settings
from database import Base, engine
from routers import auth, tasks, users
from seed import seed_demo_users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fine for a prototype; switch to Alembic migrations before the schema changes again.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if settings.seed_demo_users:
        await seed_demo_users()

    yield
    await engine.dispose()


app = FastAPI(title="Task Dashboard (Jira from Temu)", lifespan=lifespan)

app.mount("/styles", StaticFiles(directory=BASE_DIR / "templates" / "styles"), name="styles")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# --- API ---
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(tasks.router)


# --- Pages ---
# These only serve the HTML shell. The data behind them is protected by the API
# routes above (the pages redirect to the login page when no token is stored).
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_page(request: Request):
    return templates.TemplateResponse(request, "active.html")


@app.get("/completed", response_class=HTMLResponse, include_in_schema=False)
async def completed_page(request: Request):
    return templates.TemplateResponse(request, "completed.html")
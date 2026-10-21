import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.auth_routes import router as auth_router
from app.api.backlink_routes import router as backlink_router
from app.api.key_routes import router as key_router
from app.api.routes import router
from app.config import get_settings
from app.db import session_scope
from app.services.jobs import recover_interrupted_jobs


def configure_logging() -> None:
    logging.basicConfig(
        level=get_settings().log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # The SDK/httpx debug logs can include request headers; keep them quiet.
    for noisy in ("httpx", "httpx2", "httpcore", "anthropic", "openai", "google_genai", "google.genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    if get_settings().job_mode == "worker":
        yield  # the worker process owns job recovery
        return
    try:
        with session_scope() as db:
            recover_interrupted_jobs(db)
    except Exception:  # noqa: BLE001 - don't block startup; /health will still respond
        logging.getLogger(__name__).exception("Could not recover interrupted jobs (is the database migrated?)")
    yield


app = FastAPI(title="AEO Tool API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def require_proxy_secret(request: Request, call_next):
    """With AEO_PROXY_SECRET set, only the frontend's proxy may call the API (health checks excepted)."""
    secret = get_settings().proxy_secret
    if get_settings().has_key(secret) and request.url.path.startswith("/api/") and request.url.path != "/api/health":
        sent = request.headers.get("x-aeo-proxy-secret", "")
        if not hmac.compare_digest(sent.encode(), secret.get_secret_value().strip().encode()):
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"field": ".".join(str(x) for x in e["loc"][1:]), "message": str(e["msg"]).removeprefix("Value error, ")}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors[0]["message"] if errors else "Invalid input", "errors": errors})


app.include_router(auth_router)
app.include_router(router)
app.include_router(backlink_router)
app.include_router(key_router)

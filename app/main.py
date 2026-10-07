import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.database import SessionLocal
from app.routes import chat, leads


# ------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------

logger = logging.getLogger("xytralyn")


# ------------------------------------------------------------
# FASTAPI APP
# ------------------------------------------------------------

app = FastAPI(
    title="Xytralyn Core Engine",
    version="1.0.0",
)


# ------------------------------------------------------------
# GLOBAL EXCEPTION HANDLER
# ------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(
    request: Request,
    exc: Exception,
):
    request_id = getattr(
        request.state,
        "request_id",
        "unknown",
    )

    logger.exception(
        "Unhandled application exception | "
        "request_id=%s | method=%s | path=%s | error=%s",
        request_id,
        request.method,
        request.url.path,
        exc,
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "request_id": request_id,
        },
    )


# ------------------------------------------------------------
# REQUEST LOGGING / REQUEST ID
# ------------------------------------------------------------

@app.middleware("http")
async def request_logging_middleware(
    request: Request,
    call_next,
):
    request_id = str(uuid.uuid4())

    request.state.request_id = request_id

    start_time = time.perf_counter()

    try:
        response = await call_next(request)

        elapsed_ms = (
            time.perf_counter() - start_time
        ) * 1000

        response.headers["X-Request-ID"] = request_id

        logger.info(
            "HTTP request completed | "
            "request_id=%s | method=%s | path=%s | "
            "status=%s | duration_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )

        return response

    except Exception:
        elapsed_ms = (
            time.perf_counter() - start_time
        ) * 1000

        logger.exception(
            "HTTP request failed | "
            "request_id=%s | method=%s | path=%s | "
            "duration_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            elapsed_ms,
        )

        raise


# ------------------------------------------------------------
# API ROUTES
# ------------------------------------------------------------

app.include_router(
    chat.router,
    prefix="/chat",
)

app.include_router(
    leads.router,
)


# ------------------------------------------------------------
# HEALTH / ROOT ENDPOINT
# ------------------------------------------------------------

@app.get("/")
def home():
    return {
        "status": "Xytralyn Engine Running",
        "mode": "Live",
        "architecture": "Multi-Tenant",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "xytralyn-core",
    }


@app.get("/ready")
def readiness():
    db = SessionLocal()

    try:
        db.execute(text("SELECT 1"))

        return {
            "status": "ready",
            "database": "connected",
        }

    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database": "unavailable",
            },
        )

    finally:
        db.close()
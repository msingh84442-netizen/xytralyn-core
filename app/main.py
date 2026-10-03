from fastapi import FastAPI

from app.routes import chat, leads


app = FastAPI(
    title="Xytralyn Core Engine",
    version="1.0.0",
)


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
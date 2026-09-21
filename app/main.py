from fastapi import FastAPI
from app.database import engine, Base
from app.routes import chat, leads

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Xytralyn Core Engine")

app.include_router(chat.router)
app.include_router(leads.router)

@app.get("/")
def home():
    return {"status": "Xytralyn Engine Running", "mode": "Live"}
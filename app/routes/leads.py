import os
import uuid
import secrets
from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db
from app.models import Lead

router = APIRouter(prefix="/leads", tags=["Leads"])
templates = Jinja2Templates(directory="templates")
security = HTTPBasic()

# Admin Credentials (inhe baad me .env se bhi le sakte hain)
ADMIN_USERNAME = os.getenv("CRM_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("CRM_ADMIN_PASS", "admin123")

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

class StatusUpdateRequest(BaseModel):
    status: str

# 1. Protected HTML Dashboard Route
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def view_leads_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Depends(verify_credentials)
):
    leads = db.query(Lead).order_by(Lead.id.desc()).all()
    return templates.TemplateResponse(
        request=request,
        name="leads.html",
        context={"leads": leads}
    )

# 2. Update Status Route (UUID type-safe)
@router.patch("/{lead_id}/status")
@router.patch("/{lead_id}/status/")
def update_lead_status(
    lead_id: str,
    payload: StatusUpdateRequest,
    db: Session = Depends(get_db),
    username: str = Depends(verify_credentials)
):
    target_id = lead_id
    try:
        target_id = uuid.UUID(lead_id)
    except (ValueError, AttributeError):
        pass

    lead = db.query(Lead).filter(Lead.id == target_id).first()
    if not lead and target_id != lead_id:
        lead = db.query(Lead).filter(Lead.id == str(lead_id)).first()

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    lead.status = payload.status
    db.commit()
    db.refresh(lead)
    return {"status": "success", "lead_id": str(lead.id), "new_status": lead.status}

# 3. Protected JSON API Endpoint
@router.get("/api/all")
def get_all_leads_json(
    db: Session = Depends(get_db),
    username: str = Depends(verify_credentials)
):
    leads = db.query(Lead).order_by(Lead.id.desc()).all()
    return {
        "status": "success",
        "total_leads": len(leads),
        "leads": [
            {
                "id": str(lead.id),
                "phone": lead.phone,
                "name": getattr(lead, "name", None),
                "company": getattr(lead, "company", None),
                "status": lead.status,
                "created_at": str(getattr(lead, "created_at", ""))
            }
            for lead in leads
        ]
    }
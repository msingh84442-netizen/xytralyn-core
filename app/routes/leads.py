import os
import uuid
import secrets

from fastapi import (
    APIRouter,
    Depends,
    Request,
    HTTPException,
    status,
)
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import Lead, User, Membership, Tenant


router = APIRouter(
    prefix="/leads",
    tags=["Leads"],
)

templates = Jinja2Templates(
    directory="templates"
)

security = HTTPBasic()


# ============================================================
# ADMIN CREDENTIALS
# ============================================================

ADMIN_USERNAME = os.getenv(
    "CRM_ADMIN_USER"
)

ADMIN_PASSWORD = os.getenv(
    "CRM_ADMIN_PASS"
)


# ============================================================
# AUTHENTICATION
# ============================================================

def verify_credentials(
    credentials: HTTPBasicCredentials = Depends(security),
):
    """
    Verify CRM admin credentials.

    The username is mapped to User.email.
    """

    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CRM admin credentials are not configured",
        )

    correct_username = secrets.compare_digest(
        credentials.username,
        ADMIN_USERNAME,
    )

    correct_password = secrets.compare_digest(
        credentials.password,
        ADMIN_PASSWORD,
    )

    if not (
        correct_username
        and correct_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={
                "WWW-Authenticate": "Basic",
            },
        )

    return credentials.username


# ============================================================
# CURRENT ADMIN TENANT
# ============================================================

def get_current_tenant(
    db: Session,
    username: str,
) -> Tenant:
    """
    Resolve the authenticated admin's tenant through:

        User.email
            ↓
        Membership.user_id
            ↓
        Membership.tenant_id
            ↓
        Tenant
    """

    user = (
        db.query(User)
        .filter(User.email == username)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not found",
        )

    membership = (
        db.query(Membership)
        .filter(
            Membership.user_id == str(user.id),
            Membership.status == "active",
        )
        .first()
    )

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active tenant membership not found",
        )

    tenant = (
        db.query(Tenant)
        .filter(
            Tenant.id == membership.tenant_id,
            Tenant.status == "active",
        )
        .first()
    )

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active tenant not found",
        )

    return tenant


# ============================================================
# STATUS REQUEST
# ============================================================

class StatusUpdateRequest(BaseModel):
    status: str


# ============================================================
# 1. PROTECTED HTML DASHBOARD
# ============================================================

@router.get(
    "",
    response_class=HTMLResponse,
)
@router.get(
    "/",
    response_class=HTMLResponse,
)
async def view_leads_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Depends(verify_credentials),
):
    tenant = get_current_tenant(
        db,
        username,
    )

    leads = (
        db.query(Lead)
        .filter(
            Lead.tenant_id == tenant.id,
        )
        .order_by(
            Lead.id.desc(),
        )
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="leads.html",
        context={
            "leads": leads,
        },
    )


# ============================================================
# 2. UPDATE LEAD STATUS
# ============================================================

@router.patch(
    "/{lead_id}/status",
)
@router.patch(
    "/{lead_id}/status/",
)
def update_lead_status(
    lead_id: str,
    payload: StatusUpdateRequest,
    db: Session = Depends(get_db),
    username: str = Depends(verify_credentials),
):
    tenant = get_current_tenant(
        db,
        username,
    )

    target_id = lead_id

    try:
        target_id = uuid.UUID(
            lead_id
        )
    except (
        ValueError,
        AttributeError,
    ):
        pass

    lead = (
        db.query(Lead)
        .filter(
            Lead.id == target_id,
            Lead.tenant_id == tenant.id,
        )
        .first()
    )

    if not lead and target_id != lead_id:
        lead = (
            db.query(Lead)
            .filter(
                Lead.id == str(lead_id),
                Lead.tenant_id == tenant.id,
            )
            .first()
        )

    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found",
        )

    lead.status = payload.status

    db.commit()
    db.refresh(lead)

    return {
        "status": "success",
        "lead_id": str(lead.id),
        "new_status": lead.status,
        "tenant_id": str(tenant.id),
    }


# ============================================================
# 3. PROTECTED JSON API
# ============================================================

@router.get(
    "/api/all"
)
def get_all_leads_json(
    db: Session = Depends(get_db),
    username: str = Depends(verify_credentials),
):
    tenant = get_current_tenant(
        db,
        username,
    )

    leads = (
        db.query(Lead)
        .filter(
            Lead.tenant_id == tenant.id,
        )
        .order_by(
            Lead.id.desc(),
        )
        .all()
    )

    return {
        "status": "success",
        "tenant_id": str(tenant.id),
        "tenant_name": tenant.name,
        "total_leads": len(leads),
        "leads": [
            {
                "id": str(lead.id),
                "phone": lead.phone,
                "name": getattr(
                    lead,
                    "name",
                    None,
                ),
                "company": getattr(
                    lead,
                    "company",
                    None,
                ),
                "status": lead.status,
                "created_at": str(
                    getattr(
                        lead,
                        "created_at",
                        "",
                    )
                ),
            }
            for lead in leads
        ],
    }
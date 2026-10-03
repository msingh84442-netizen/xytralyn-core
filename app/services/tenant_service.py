from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    Tenant,
    WhatsAppAccount,
)


# ============================================================
# GET TENANT BY WHATSAPP PHONE NUMBER ID
# ============================================================

def get_tenant_by_phone_number_id(
    db: Session,
    phone_number_id: str,
) -> Optional[Tenant]:

    if not phone_number_id:
        return None

    whatsapp_account = (
        db.query(WhatsAppAccount)
        .filter(
            WhatsAppAccount.phone_number_id
            == phone_number_id
        )
        .first()
    )

    if not whatsapp_account:
        return None

    tenant = (
        db.query(Tenant)
        .filter(
            Tenant.id == whatsapp_account.tenant_id
        )
        .first()
    )

    return tenant


# ============================================================
# GET WHATSAPP ACCOUNT
# ============================================================

def get_whatsapp_account(
    db: Session,
    phone_number_id: str,
) -> Optional[WhatsAppAccount]:

    if not phone_number_id:
        return None

    return (
        db.query(WhatsAppAccount)
        .filter(
            WhatsAppAccount.phone_number_id
            == phone_number_id
        )
        .first()
    )
import uuid

from app.database import SessionLocal
from app.models import Tenant, Lead, Message, Ticket, WhatsAppAccount
from app.services.ticket_service import (
    create_ticket,
    get_ticket,
    get_customer_tickets,
    get_tenant_tickets,
)
from app.services.tenant_service import (
    get_tenant_by_phone_number_id,
)


def main():
    db = SessionLocal()

    tenant_a = None
    tenant_b = None

    try:
        # ---------------------------------------------------------
        # 1. Create two temporary tenants
        # ---------------------------------------------------------
        tenant_a = Tenant(
            id=uuid.uuid4(),
            name="Isolation Test A",
            slug=f"isolation-test-a-{uuid.uuid4().hex[:8]}",
            industry="real_estate",
            status="active",
        )

        tenant_b = Tenant(
            id=uuid.uuid4(),
            name="Isolation Test B",
            slug=f"isolation-test-b-{uuid.uuid4().hex[:8]}",
            industry="clinic",
            status="active",
        )

        db.add_all([tenant_a, tenant_b])
        db.commit()

        print("\n=== TENANTS CREATED ===")
        print("Tenant A:", tenant_a.id)
        print("Tenant B:", tenant_b.id)

        # ---------------------------------------------------------
        # 2. Create Lead A and Lead B
        # ---------------------------------------------------------
        lead_a = Lead(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            name="Customer A",
            phone="+910000000001",
            status="active",
        )

        lead_b = Lead(
            id=uuid.uuid4(),
            tenant_id=tenant_b.id,
            name="Customer B",
            phone="+910000000002",
            status="active",
        )

        db.add_all([lead_a, lead_b])
        db.commit()

        # ---------------------------------------------------------
        # 3. Create Message A and Message B
        # ---------------------------------------------------------
        message_a = Message(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            sender_phone="+910000000001",
            content="Message belonging to Tenant A",
            agent_used="sales",
            sender_type="customer",
        )

        message_b = Message(
            id=uuid.uuid4(),
            tenant_id=tenant_b.id,
            sender_phone="+910000000002",
            content="Message belonging to Tenant B",
            agent_used="support",
            sender_type="customer",
        )

        db.add_all([message_a, message_b])
        db.commit()

        # ---------------------------------------------------------
        # 4. Create Ticket A and Ticket B
        # ---------------------------------------------------------
        ticket_a = create_ticket(
            db=db,
            tenant_id=tenant_a.id,
            customer_phone="+919876543211",
            subject="Tenant A Ticket",
            description="Private ticket for Tenant A",
            category="general",
            priority="medium",
        )

        ticket_b = create_ticket(
            db=db,
            tenant_id=tenant_b.id,
            customer_phone="+919876543211",
            subject="Tenant B Ticket",
            description="Private ticket for Tenant B",
            category="general",
            priority="medium",
        )

        print("\n=== RECORDS CREATED ===")
        print("Lead A:", lead_a.id)
        print("Lead B:", lead_b.id)
        print("Ticket A:", ticket_a)
        print("Ticket B:", ticket_b)

        # ---------------------------------------------------------
        # 5. TEST LEAD ISOLATION
        # ---------------------------------------------------------
        tenant_a_leads = (
            db.query(Lead)
            .filter(Lead.tenant_id == tenant_a.id)
            .all()
        )

        tenant_b_leads = (
            db.query(Lead)
            .filter(Lead.tenant_id == tenant_b.id)
            .all()
        )

        assert len(tenant_a_leads) == 1
        assert tenant_a_leads[0].name == "Customer A"

        assert len(tenant_b_leads) == 1
        assert tenant_b_leads[0].name == "Customer B"

        print("\n[PASS] Lead isolation")

        # ---------------------------------------------------------
        # 6. TEST MESSAGE ISOLATION
        # ---------------------------------------------------------
        tenant_a_messages = (
            db.query(Message)
            .filter(Message.tenant_id == tenant_a.id)
            .all()
        )

        tenant_b_messages = (
            db.query(Message)
            .filter(Message.tenant_id == tenant_b.id)
            .all()
        )

        assert len(tenant_a_messages) == 1
        assert tenant_a_messages[0].content == "Message belonging to Tenant A"

        assert len(tenant_b_messages) == 1
        assert tenant_b_messages[0].content == "Message belonging to Tenant B"

        print("[PASS] Message isolation")

        # ---------------------------------------------------------
        # 7. TEST TICKET ISOLATION
        # ---------------------------------------------------------
        tenant_a_tickets = get_tenant_tickets(
            db=db,
            tenant_id=tenant_a.id,
        )

        tenant_b_tickets = get_tenant_tickets(
            db=db,
            tenant_id=tenant_b.id,
        )

        assert len(tenant_a_tickets) == 1
        assert tenant_a_tickets[0].subject == "Tenant A Ticket"

        assert len(tenant_b_tickets) == 1
        assert tenant_b_tickets[0].subject == "Tenant B Ticket"

        print("[PASS] Ticket isolation")

        # ---------------------------------------------------------
        # 8. CROSS-TENANT TICKET ACCESS MUST FAIL
        # ---------------------------------------------------------
        cross_ticket = get_ticket(
            db=db,
            tenant_id=tenant_b.id,
            ticket_number=ticket_a["ticket"]["ticket_number"],
        )

        assert cross_ticket is None

        print("[PASS] Cross-tenant ticket access blocked")

        # ---------------------------------------------------------
        # 9. CUSTOMER TICKET ISOLATION
        # ---------------------------------------------------------
        wrong_customer_tickets = get_customer_tickets(
            db=db,
            tenant_id=tenant_b.id,
            customer_phone="+910000000001",
        )

        assert wrong_customer_tickets == []

        print("[PASS] Cross-tenant customer ticket access blocked")

        # ---------------------------------------------------------
        # 10. TEST WHATSAPP ACCOUNT → TENANT RESOLUTION
        # ---------------------------------------------------------
        wa_a = WhatsAppAccount(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            phone_number_id=f"test-phone-a-{uuid.uuid4().hex[:8]}",
            waba_id=f"test-waba-a-{uuid.uuid4().hex[:8]}",
            display_phone_number="+910000000011",
            access_token="TEST_TOKEN_A",
            verify_token="TEST_VERIFY_A",
            admin_whatsapp_number="+910000000001",
            status="active",
        )

        wa_b = WhatsAppAccount(
            id=uuid.uuid4(),
            tenant_id=tenant_b.id,
            phone_number_id=f"test-phone-b-{uuid.uuid4().hex[:8]}",
            waba_id=f"test-waba-b-{uuid.uuid4().hex[:8]}",
            display_phone_number="+910000000022",
            access_token="TEST_TOKEN_B",
            verify_token="TEST_VERIFY_B",
            admin_whatsapp_number="+910000000002",
            status="active",
        )

        db.add_all([wa_a, wa_b])
        db.commit()

        resolved_a = get_tenant_by_phone_number_id(
            db,
            wa_a.phone_number_id,
        )

        resolved_b = get_tenant_by_phone_number_id(
            db,
            wa_b.phone_number_id,
        )

        assert resolved_a is not None
        assert resolved_b is not None

        assert resolved_a.id == tenant_a.id
        assert resolved_b.id == tenant_b.id

        print("[PASS] WhatsApp → Tenant resolution")

        # ---------------------------------------------------------
        # 11. FINAL RESULT
        # ---------------------------------------------------------
        print("\n========================================")
        print("TENANT ISOLATION TEST PASSED")
        print("========================================")

    finally:
        # ---------------------------------------------------------
        # CLEANUP TEST DATA ONLY
        # ---------------------------------------------------------
        if tenant_a is not None:
            db.query(WhatsAppAccount).filter(
                WhatsAppAccount.tenant_id == tenant_a.id
            ).delete(synchronize_session=False)

            db.query(Ticket).filter(
                Ticket.tenant_id == tenant_a.id
            ).delete(synchronize_session=False)

            db.query(Message).filter(
                Message.tenant_id == tenant_a.id
            ).delete(synchronize_session=False)

            db.query(Lead).filter(
                Lead.tenant_id == tenant_a.id
            ).delete(synchronize_session=False)

        if tenant_b is not None:
            db.query(WhatsAppAccount).filter(
                WhatsAppAccount.tenant_id == tenant_b.id
            ).delete(synchronize_session=False)

            db.query(Ticket).filter(
                Ticket.tenant_id == tenant_b.id
            ).delete(synchronize_session=False)

            db.query(Message).filter(
                Message.tenant_id == tenant_b.id
            ).delete(synchronize_session=False)

            db.query(Lead).filter(
                Lead.tenant_id == tenant_b.id
            ).delete(synchronize_session=False)

        if tenant_a is not None:
            db.delete(tenant_a)

        if tenant_b is not None:
            db.delete(tenant_b)

        db.commit()
        db.close()

        print("\nTest data cleaned up.")


if __name__ == "__main__":
    main()
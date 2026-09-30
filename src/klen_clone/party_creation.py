"""Approval-gated target-side customer and supplier creation."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, func, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import OperationalAuditEvent, OperationalBase, utc_now
from .operational_masters import OperationalPartyMaster
from .country_catalog import country_code as normalize_country_code, currency_code as normalize_currency_code, market_scope


class OperationalPartyCreationRequest(OperationalBase):
    __tablename__ = "operational_party_creation_requests"
    __table_args__ = (
        CheckConstraint("party_kind IN ('customer','supplier')", name="ck_party_request_kind"),
        CheckConstraint("status IN ('pending','approved','rejected')", name="ck_party_request_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    party_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    party_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    legal_or_business_name: Mapped[str] = mapped_column(String(500), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(320))
    mobile: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    tax_number: Mapped[str | None] = mapped_column(String(120))
    country_code: Mapped[str | None] = mapped_column(String(2))
    preferred_currency_code: Mapped[str | None] = mapped_column(String(3))
    tax_registration_type: Mapped[str | None] = mapped_column(String(20))
    tax_country_code: Mapped[str | None] = mapped_column(String(2))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)


def _clean_optional(value: str | None) -> str | None:
    return value.strip() or None if value else None


def _check_duplicate(session: Session, *, code: str, kind: str, name: str,
                     tax_number: str | None, tax_country_code: str | None,
                     exclude_request: int | None = None) -> None:
    if session.scalar(select(OperationalPartyMaster.id).where(OperationalPartyMaster.party_code == code)):
        raise ValueError("Party code already exists")
    if session.scalar(select(OperationalPartyMaster.id).where(
        OperationalPartyMaster.party_kind.in_((kind, "both")),
        func.lower(OperationalPartyMaster.legal_or_business_name) == name.casefold())):
        raise ValueError("A party with this business name already exists")
    if tax_number and session.scalar(select(OperationalPartyMaster.id).where(
        OperationalPartyMaster.tax_number == tax_number,
        or_(OperationalPartyMaster.tax_country_code == tax_country_code,
            OperationalPartyMaster.tax_country_code.is_(None)))):
        raise ValueError("Tax number already belongs to another party")
    pending = list(session.scalars(select(OperationalPartyCreationRequest).where(
        OperationalPartyCreationRequest.status == "pending",
        OperationalPartyCreationRequest.id != (exclude_request or -1))))
    for request in pending:
        if request.party_code == code:
            raise ValueError("Party code already has a pending request")
        if request.party_kind == kind and request.legal_or_business_name.casefold() == name.casefold():
            raise ValueError("Business name already has a pending request")
        if tax_number and request.tax_number == tax_number and (
                request.tax_country_code is None or request.tax_country_code == tax_country_code):
            raise ValueError("Tax number already has a pending request")


def propose_party(session: Session, *, party_code: str, party_kind: str,
                  legal_or_business_name: str, actor: str, contact_name: str | None = None,
                  email: str | None = None, mobile: str | None = None,
                  address: str | None = None, tax_number: str | None = None,
                  country_code: str | None = None, preferred_currency_code: str | None = None,
                  tax_registration_type: str | None = None,
                  tax_country_code: str | None = None) -> OperationalPartyCreationRequest:
    code = party_code.strip().upper()
    kind = party_kind.strip().lower()
    name = " ".join(legal_or_business_name.split())
    if kind not in {"customer", "supplier"}:
        raise ValueError("Party kind must be customer or supplier")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{1,79}", code):
        raise ValueError("Party code must have 2–80 letters, numbers, dots, hyphens or underscores")
    if not name or len(name) > 500:
        raise ValueError("Business name is required and must be at most 500 characters")
    if not country_code or not preferred_currency_code:
        raise ValueError("Country and preferred currency are required for new parties")
    country = normalize_country_code(country_code)
    currency = normalize_currency_code(preferred_currency_code)
    tax = _clean_optional(tax_number)
    tax_type = _clean_optional(tax_registration_type)
    tax_country = normalize_country_code(tax_country_code) if tax_country_code else None
    if tax:
        if tax_type not in {"vat", "gst", "other"}:
            raise ValueError("Choose the tax registration type for the supplied tax ID")
        if not tax_country:
            raise ValueError("Choose the issuing country for the supplied tax ID")
    elif tax_type or tax_country:
        raise ValueError("Tax registration details require a tax ID")
    _check_duplicate(session, code=code, kind=kind, name=name,
                     tax_number=tax, tax_country_code=tax_country)
    request = OperationalPartyCreationRequest(request_key=str(uuid.uuid4()), party_code=code,
        party_kind=kind, legal_or_business_name=name, contact_name=_clean_optional(contact_name),
        email=_clean_optional(email), mobile=_clean_optional(mobile),
        address=_clean_optional(address), tax_number=tax, country_code=country,
        preferred_currency_code=currency, tax_registration_type=tax_type,
        tax_country_code=tax_country, created_by=actor)
    session.add(request)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="master.party.requested",
        actor=actor, resource_key=request.request_key, detail=f"{kind} {code}; pending independent approval"))
    session.commit()
    return request


def decide_party(session: Session, request_key: str, *, action: str,
                 actor: str, note: str) -> OperationalPartyCreationRequest:
    if action not in {"approve", "reject"}:
        raise ValueError("Unsupported party decision")
    request = session.scalar(select(OperationalPartyCreationRequest).where(
        OperationalPartyCreationRequest.request_key == request_key).with_for_update())
    if not request:
        raise ValueError("Party request not found")
    if request.status != "pending":
        raise ValueError("Party request has already been decided")
    if request.created_by.casefold() == actor.casefold():
        raise ValueError("Maker cannot approve or reject their own party request")
    reason = note.strip()
    if len(reason) < 5:
        raise ValueError("Decision note must contain at least five characters")
    if action == "approve":
        _check_duplicate(session, code=request.party_code, kind=request.party_kind,
            name=request.legal_or_business_name, tax_number=request.tax_number,
            tax_country_code=request.tax_country_code,
            exclude_request=request.id)
        fields = {key: getattr(request, key) for key in (
            "party_code", "party_kind", "legal_or_business_name", "contact_name",
            "email", "mobile", "address", "tax_number", "country_code",
            "preferred_currency_code", "tax_registration_type", "tax_country_code")}
        checksum = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()
        session.add(OperationalPartyMaster(party_key=str(uuid.uuid4()), **fields,
            status="active", revision=1, source_promoted=False,
            source_snapshot_name="target-created", source_checksum=checksum,
            created_by=request.created_by, updated_by=actor))
    request.status = "approved" if action == "approve" else "rejected"
    request.decided_by, request.decided_at, request.decision_note = actor, utc_now(), reason
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),
        event_type=f"master.party.{request.status}", actor=actor,
        resource_key=request.request_key, detail=f"{request.party_kind} {request.party_code}; {reason}"))
    session.commit()
    return request


def party_request_payload(request: OperationalPartyCreationRequest) -> dict:
    payload = {key: getattr(request, key) for key in (
        "request_key", "party_code", "party_kind", "legal_or_business_name",
        "contact_name", "email", "mobile", "address", "tax_number", "country_code",
        "preferred_currency_code", "tax_registration_type", "tax_country_code", "status",
        "created_by", "created_at", "decided_by", "decided_at", "decision_note")}
    payload["market_scope"] = market_scope(request.country_code)
    return payload

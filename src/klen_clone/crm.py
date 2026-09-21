"""Controlled CRM workflow for the target ERP; no source records are modified."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .operational import OperationalAuditEvent, OperationalBase


def _now(): return datetime.now(timezone.utc)


class OperationalCrmLead(OperationalBase):
    __tablename__ = "operational_crm_leads"
    __table_args__ = (CheckConstraint("status IN ('new','qualified','proposal_submitted','won','lost')", name="ck_crm_lead_status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    lead_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    company_name: Mapped[str] = mapped_column(String(300), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    owner: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="new")
    next_follow_up_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    activities: Mapped[list["OperationalCrmActivity"]] = relationship(cascade="all, delete-orphan")
    proposals: Mapped[list["OperationalCrmProposal"]] = relationship(cascade="all, delete-orphan")


class OperationalCrmActivity(OperationalBase):
    __tablename__ = "operational_crm_activities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activity_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    lead_id: Mapped[int] = mapped_column(ForeignKey("operational_crm_leads.id", ondelete="CASCADE"), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)


class OperationalCrmProposal(OperationalBase):
    __tablename__ = "operational_crm_proposals"
    __table_args__ = (CheckConstraint("status IN ('draft','submitted','approved','rejected')", name="ck_crm_proposal_status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    lead_id: Mapped[int] = mapped_column(ForeignKey("operational_crm_leads.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    value_aed: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


def _audit(s, typ, actor, key, detail):
    s.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=typ, actor=actor, resource_key=key, detail=detail))

def create_lead(s: Session, *, company_name, contact_name, contact_email, source, owner, follow_up_at, actor):
    key=str(uuid.uuid4()); row=OperationalCrmLead(lead_key=key, lead_no=f"LEAD-{key[:8].upper()}", company_name=company_name.strip(), contact_name=contact_name, contact_email=contact_email, source=source.strip(), owner=owner.strip(), next_follow_up_at=follow_up_at, created_by=actor)
    s.add(row); s.flush(); _audit(s,"crm.lead.created",actor,key,"Target-side CRM lead"); s.commit(); return row

def add_activity(s: Session, *, lead_key, activity_type, note, due_at, actor):
    lead=s.scalar(select(OperationalCrmLead).where(OperationalCrmLead.lead_key==lead_key))
    if not lead: raise ValueError("CRM lead not found")
    row=OperationalCrmActivity(activity_key=str(uuid.uuid4()),lead_id=lead.id,activity_type=activity_type,note=note.strip(),due_at=due_at,completed_by=actor)
    lead.next_follow_up_at=due_at or lead.next_follow_up_at; lead.revision+=1; s.add(row); _audit(s,"crm.activity.logged",actor,lead_key,activity_type); s.commit(); return row

def create_proposal(s: Session, *, lead_key, title, value_aed, actor):
    lead=s.scalar(select(OperationalCrmLead).where(OperationalCrmLead.lead_key==lead_key))
    if not lead: raise ValueError("CRM lead not found")
    row=OperationalCrmProposal(proposal_key=str(uuid.uuid4()),lead_id=lead.id,title=title.strip(),value_aed=value_aed,created_by=actor); lead.status="proposal_submitted"; lead.revision+=1; s.add(row); s.flush(); _audit(s,"crm.proposal.created",actor,row.proposal_key,title); s.commit(); return row

def decide_proposal(s: Session, *, proposal_key, expected_revision, decision, note, actor):
    row=s.scalar(select(OperationalCrmProposal).where(OperationalCrmProposal.proposal_key==proposal_key))
    if not row: raise ValueError("CRM proposal not found")
    if row.created_by==actor: raise PermissionError("Maker-checker control prevents proposal self-approval")
    if row.status!="draft" or row.revision!=expected_revision: raise ValueError("Proposal is no longer awaiting review")
    row.status=decision; row.approved_by=actor; row.revision+=1; _audit(s,f"crm.proposal.{decision}",actor,row.proposal_key,note.strip()); s.commit(); return row

def crm_workspace_payload(s: Session):
    leads=list(s.scalars(select(OperationalCrmLead).order_by(OperationalCrmLead.created_at.desc())))
    proposals=list(s.scalars(select(OperationalCrmProposal).order_by(OperationalCrmProposal.id.desc())))
    lead_keys={x.id:x.lead_key for x in leads}
    return {"controls":{"leads":len(leads),"follow_ups_due":sum(x.next_follow_up_at is not None and x.next_follow_up_at<=_now() for x in leads),"pending_proposals":sum(x.status=="draft" for x in proposals),"posting_enabled":False},"leads":[{"lead_key":x.lead_key,"lead_no":x.lead_no,"company_name":x.company_name,"contact_name":x.contact_name,"source":x.source,"owner":x.owner,"status":x.status,"next_follow_up_at":x.next_follow_up_at,"revision":x.revision} for x in leads],"proposals":[{"proposal_key":x.proposal_key,"lead_key":lead_keys.get(x.lead_id),"title":x.title,"value_aed":x.value_aed,"status":x.status,"created_by":x.created_by,"revision":x.revision} for x in proposals],"boundary":{"test_data_only":True,"posting_performed":False,"source_read_only":True}}

"""SQLAlchemy models for AI Outreach Pro.

All tables from the architecture document live here so later phases only add
service logic, not schema churn. JSON columns keep SQLite (dev/tests) and
PostgreSQL (production) compatible.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    physical_address: Mapped[str] = mapped_column(String(500), default="")
    sender_name: Mapped[str] = mapped_column(String(200), default="")
    daily_send_limit: Mapped[int] = mapped_column(Integer, default=50)
    hourly_send_limit: Mapped[int] = mapped_column(Integer, default=10)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="member")  # admin|manager|member
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # bump to revoke all tokens
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    org: Mapped[Organization] = relationship()


class Integration(Base):
    __tablename__ = "integrations"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50))  # smtp|gmail|openai|apollo|hunter|zerobounce|loom
    label: Mapped[str] = mapped_column(String(200), default="")
    encrypted_credentials: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="disconnected")
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("org_id", "dedupe_key", name="uq_lead_dedupe"),
        Index("ix_leads_org_status", "org_id", "status"),
        Index("ix_leads_org_score", "org_id", "score"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_name: Mapped[str] = mapped_column(String(255), index=True)
    website: Mapped[str] = mapped_column(String(500), default="")
    industry: Mapped[str] = mapped_column(String(120), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    company_size: Mapped[str] = mapped_column(String(50), default="")
    niche: Mapped[str] = mapped_column(String(200), default="")
    contact_name: Mapped[str] = mapped_column(String(200), default="")
    contact_title: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(255), default="", index=True)
    email_status: Mapped[str] = mapped_column(String(30), default="unverified")  # unverified|valid|risky|invalid
    source: Mapped[str] = mapped_column(String(50), default="manual")
    source_url: Mapped[str] = mapped_column(String(500), default="")
    score: Mapped[int] = mapped_column(Integer, default=0)
    tier: Mapped[str] = mapped_column(String(10), default="cold")  # hot|warm|cold
    status: Mapped[str] = mapped_column(String(30), default="new")  # new|contacted|replied|meeting|won|lost|unsubscribed
    category: Mapped[str] = mapped_column(String(100), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    dedupe_key: Mapped[str] = mapped_column(String(300), default="")
    region_flag: Mapped[str] = mapped_column(String(10), default="")  # e.g. EU/UK warning
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchReport(Base):
    __tablename__ = "research_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    products_services: Mapped[str] = mapped_column(Text, default="")
    pain_points: Mapped[str] = mapped_column(Text, default="")
    opportunities: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LeadScoreEvent(Base):
    __tablename__ = "lead_score_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    tier: Mapped[str] = mapped_column(String(10))
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    model_version: Mapped[str] = mapped_column(String(50), default="rules-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    tone: Mapped[str] = mapped_column(String(50), default="professional")
    status: Mapped[str] = mapped_column(String(30), default="draft")  # draft|pending_approval|approved|running|paused|completed
    sender_integration_id: Mapped[int | None] = mapped_column(ForeignKey("integrations.id"), nullable=True)
    schedule: Mapped[dict] = mapped_column(JSON, default=dict)
    followup_intervals: Mapped[list] = mapped_column(JSON, default=lambda: [3, 7])
    max_followups: Mapped[int] = mapped_column(Integer, default=2)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CampaignLead(Base):
    __tablename__ = "campaign_leads"
    __table_args__ = (
        UniqueConstraint("campaign_id", "lead_id", name="uq_campaign_lead"),
        Index("ix_campaign_leads_due", "state", "next_send_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    state: Mapped[str] = mapped_column(String(30), default="pending")  # pending|active|replied|bounced|opted_out|completed
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    next_send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailDraft(Base):
    __tablename__ = "email_drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_lead_id: Mapped[int | None] = mapped_column(ForeignKey("campaign_leads.id"), nullable=True, index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    step: Mapped[int] = mapped_column(Integer, default=0)
    variant: Mapped[str] = mapped_column(String(20), default="medium")  # short|medium|detailed
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|sent
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_org_dir_sent", "org_id", "direction", "sent_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True, index=True)
    direction: Mapped[str] = mapped_column(String(5))  # out|in
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    provider_message_id: Mapped[str] = mapped_column(String(300), default="")
    thread_id: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|sent|delivered|bounced|failed|received
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReplyClassification(Base):
    __tablename__ = "reply_classifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), unique=True)
    label: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    suggested_response: Mapped[str] = mapped_column(Text, default="")
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))  # campaign|reply|assistant_run
    entity_id: Mapped[int] = mapped_column(Integer)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Suppression(Base):
    __tablename__ = "suppression_list"
    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_suppression"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    reason: Mapped[str] = mapped_column(String(30), default="manual")  # unsubscribed|bounced|complaint|manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Video(Base):
    __tablename__ = "videos"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True)
    script: Mapped[str] = mapped_column(Text, default="")
    intro: Mapped[str] = mapped_column(Text, default="")
    thumbnail_url: Mapped[str] = mapped_column(String(500), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    loom_url: Mapped[str] = mapped_column(String(500), default="")
    source: Mapped[str] = mapped_column(String(20), default="loom_manual")
    status: Mapped[str] = mapped_column(String(30), default="script_ready")  # script_ready|awaiting_recording|published
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = not available
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    entity: Mapped[str] = mapped_column(String(50), default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssistantRun(Base):
    __tablename__ = "assistant_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    command: Mapped[str] = mapped_column(Text)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="planned")
    pending_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

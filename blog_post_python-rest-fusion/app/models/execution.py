from uuid import uuid4

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.base import Base, ModelBase


class Execution(ModelBase):
    __tablename__ = "executions"
    __table_args__ = (UniqueConstraint("external_id", name="ux_executions_external_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source = Column(String(20), nullable=False, default="api")
    kind = Column(String(20), nullable=False)
    campaign_id = Column(Integer, nullable=True, index=True)
    post_id = Column(Integer, nullable=True, index=True)
    external_id = Column(String(160), nullable=True, index=True)
    payload_hash = Column(String(64), nullable=True)
    status = Column(String(20), nullable=False, default="queued")
    title = Column(Text, nullable=True)
    result = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("executions.id", ondelete="CASCADE"), nullable=False, index=True)
    ts = Column(DateTime, nullable=False)
    level = Column(String(10), nullable=False)
    message = Column(Text, nullable=False)

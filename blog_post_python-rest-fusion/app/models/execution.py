from sqlalchemy import Column, Integer, String, Text, UniqueConstraint

from app.models.base import ModelBase


class Execution(ModelBase):
    __tablename__ = "executions"
    __table_args__ = (UniqueConstraint("external_id", name="ux_executions_external_id"),)

    id = Column(Integer, primary_key=True)
    external_id = Column(String(160), nullable=True, index=True)
    payload_hash = Column(String(64), nullable=True)
    source = Column(String(32), nullable=False, default="local")
    capability = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="running")
    result = Column(Text, nullable=True)
    error = Column(Text, nullable=True)

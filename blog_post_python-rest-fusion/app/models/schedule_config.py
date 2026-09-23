from sqlalchemy import Boolean, Column, Integer, String

from app.models.base import ModelBase


class ScheduleConfig(ModelBase):
    __tablename__ = "schedule_config"

    id = Column(Integer, primary_key=True, default=1)
    hour = Column(String(5), nullable=False, default="02:00")
    timezone = Column(String(64), nullable=False, default="America/Bogota")
    enabled = Column(Boolean, nullable=False, default=True)

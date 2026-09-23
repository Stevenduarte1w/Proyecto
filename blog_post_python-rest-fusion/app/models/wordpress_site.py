from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import ModelBase


class WordPressSite(ModelBase):
    __tablename__ = "wordpress_sites"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    url = Column(String(500), nullable=False)
    username = Column(String(255), nullable=False)
    credential_ref = Column(String(120), nullable=False, unique=True)
    yoast_enabled = Column(Boolean, nullable=False, default=True)
    is_active = Column(Boolean, nullable=False, default=True)

    campaigns = relationship("Campaign", back_populates="wordpress_site")

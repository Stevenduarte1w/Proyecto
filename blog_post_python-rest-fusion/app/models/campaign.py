from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from app.models.base import ModelBase


class Campaign(ModelBase):
    """Campaign Model"""

    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    wordpress_site_id = Column(Integer, ForeignKey("wordpress_sites.id"), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    wordpress_site = relationship("WordPressSite", back_populates="campaigns")

    posts = relationship(
        "Post", back_populates="campaign", cascade="all, delete-orphan"
    )

    optimized_posts = relationship(
        "OptimizedPost", back_populates="campaign", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return super().__repr__()

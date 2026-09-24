from sqlalchemy import Column, ForeignKey, Integer, String, DateTime, Text
from sqlalchemy.orm import relationship
from app.models.base import ModelBase


class OptimizedPost(ModelBase):
    """Optimized Post Model"""

    __tablename__ = "optimized_posts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    seo_title = Column(String(255), nullable=True)
    keywords = Column(String(255), nullable=True)
    keywords_urls = Column(String(255), nullable=True)
    conclusions = Column(Text, nullable=True)
    conclusions_urls = Column(Text, nullable=True)
    citys = Column(Text, nullable=True)
    citys_urls = Column(Text, nullable=True)
    external = Column(String(255), nullable=True)
    external_url = Column(String(255), nullable=True)
    hashtags = Column(Text, nullable=True)
    categories = Column(Text, nullable=True)
    language = Column(String(10), nullable=True)
    image = Column(Text, nullable=True)
    image_prompt = Column(Text, nullable=True)
    date = Column(DateTime, nullable=False)
    edition_url = Column(String(255), nullable=True)

    campaign_id = Column(
        Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    campaign = relationship("Campaign", back_populates="optimized_posts")
    wp_post_id = Column(Integer, nullable=True)
    wp_route = Column(String(16), nullable=True)
    slug = Column(String(255), nullable=True)
    previous_snapshot = Column(Text, nullable=True)
    last_error = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    state = Column(String(24), nullable=False, default="pending", index=True)
    claimed_at = Column(DateTime, nullable=True)
    optimized_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return super().__repr__()

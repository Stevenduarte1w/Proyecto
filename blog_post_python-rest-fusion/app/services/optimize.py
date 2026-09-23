from sqlalchemy.orm import Session
from app.models.optimize import OptimizedPost
from app.schemas.optimize import (
    OptimizedPostCreate,
    OptimizedPostResponse,
    OptimizedPostUpdate,
)
from typing import List, Optional
from datetime import datetime, time, timedelta


class OptimizedPostService:
    """Service for OptimizedPost model"""

    def __init__(self, db: Session):
        self.db = db

    def create_optimized_post(
        self, optimized_post_data: OptimizedPostCreate
    ) -> OptimizedPostResponse:
        new_optimized_post = OptimizedPost(**optimized_post_data.model_dump())
        self.db.add(new_optimized_post)
        self.db.commit()
        self.db.refresh(new_optimized_post)
        return OptimizedPostResponse.model_validate(new_optimized_post)

    def get_optimized_post(
        self, optimized_post_id: int
    ) -> Optional[OptimizedPostResponse]:
        query = self.db.query(OptimizedPost).filter(
            OptimizedPost.id == optimized_post_id
        )
        optimized_post = query.first()
        if not optimized_post:
            return None
        return OptimizedPostResponse.model_validate(optimized_post)

    def get_post_by_campaign(self, campaign_id: int) -> List[OptimizedPostResponse]:
        query = self.db.query(OptimizedPost).filter(
            OptimizedPost.campaign_id == campaign_id
        )
        posts = query.all()
        return [OptimizedPostResponse.model_validate(post) for post in posts]

    def get_all_optimized_posts(self) -> List[OptimizedPostResponse]:
        posts = self.db.query(OptimizedPost).all()
        return [OptimizedPostResponse.model_validate(post) for post in posts]

    def get_today_optimized_posts(self) -> List[OptimizedPostResponse]:
        today = datetime.now().date()
        start = datetime.combine(today, time.min)
        end = start + timedelta(days=1)
        posts = self.db.query(OptimizedPost).filter(
            OptimizedPost.date >= start, OptimizedPost.date < end
        ).all()
        return [OptimizedPostResponse.model_validate(post) for post in posts]

    def update_optimized_post(
        self, optimized_post_id: int, optimized_post_data: OptimizedPostUpdate
    ) -> Optional[OptimizedPostResponse]:
        query = self.db.query(OptimizedPost).filter(
            OptimizedPost.id == optimized_post_id
        )
        optimized_post = query.first()
        if not optimized_post:
            return None
        for key, value in optimized_post_data.model_dump(exclude_unset=True).items():
            setattr(optimized_post, key, value)
        self.db.commit()
        self.db.refresh(optimized_post)
        return OptimizedPostResponse.model_validate(optimized_post)

    def publish_optimized_post(
        self, optimized_post_id: int
    ) -> Optional[OptimizedPostResponse]:
        query = self.db.query(OptimizedPost).filter(
            OptimizedPost.id == optimized_post_id
        )
        optimized_post = query.first()
        if not optimized_post:
            return None
        optimized_post.status = True
        optimized_post.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(optimized_post)
        return OptimizedPostResponse.model_validate(optimized_post)

    def delete_optimized_post(self, optimized_post_id: int) -> bool:
        query = self.db.query(OptimizedPost).filter(
            OptimizedPost.id == optimized_post_id
        )
        optimized_post = query.first()
        if not optimized_post:
            return False
        self.db.delete(optimized_post)
        self.db.commit()
        return True

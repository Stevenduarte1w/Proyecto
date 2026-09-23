from sqlalchemy.orm import Session
from app.models.post import Post
from app.schemas.post import PostCreate, PostResponse, PostUpdate
from typing import List, Optional
from datetime import datetime, time, timedelta


class PostService:
    """Service for managing posts"""

    def __init__(self, db: Session):
        self.db = db

    def create_post(self, post_data: PostCreate) -> PostResponse:
        """Create a new post"""
        new_post = Post(**post_data.model_dump())
        self.db.add(new_post)
        self.db.commit()
        self.db.refresh(new_post)
        return PostResponse.model_validate(new_post)

    def get_post(self, post_id: int) -> Optional[PostResponse]:
        """Get a post by ID"""
        query = self.db.query(Post).filter(Post.id == post_id)
        post = query.first()
        if not post:
            return None
        return PostResponse.model_validate(post)

    def get_posts_by_campaign(self, campaign_id: int) -> List[PostResponse]:
        """Get all posts for a specific campaign"""
        query = self.db.query(Post).filter(Post.campaign_id == campaign_id)
        posts = query.all()
        return [PostResponse.model_validate(p) for p in posts]

    def get_all_posts(self) -> List[PostResponse]:
        """Get all posts"""
        posts = self.db.query(Post).all()
        return [PostResponse.model_validate(p) for p in posts]

    def get_today_posts(self) -> List[PostResponse]:
        """Get all posts created today"""
        today = datetime.now().date()
        start = datetime.combine(today, time.min)
        end = start + timedelta(days=1)
        posts = self.db.query(Post).filter(Post.date >= start, Post.date < end).all()
        return [PostResponse.model_validate(p) for p in posts]

    def update_post(
        self, post_id: int, post_data: PostUpdate
    ) -> Optional[PostResponse]:
        """Update an existing post"""
        query = self.db.query(Post).filter(Post.id == post_id)
        post = query.first()
        if not post:
            return None
        for key, value in post_data.model_dump(exclude_unset=True).items():
            setattr(post, key, value)

        post.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(post)
        return PostResponse.model_validate(post)

    def publish_post(self, post_id: int) -> Optional[PostResponse]:
        """Mark a post as published"""
        query = self.db.query(Post).filter(Post.id == post_id)
        post = query.first()
        if not post:
            return None

        post.status = True
        post.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(post)
        return PostResponse.model_validate(post)

    def delete_post(self, post_id: int) -> bool:
        """Delete a post by ID"""
        query = self.db.query(Post).filter(Post.id == post_id)
        post = query.first()
        if not post:
            return False

        self.db.delete(post)
        self.db.commit()
        return True

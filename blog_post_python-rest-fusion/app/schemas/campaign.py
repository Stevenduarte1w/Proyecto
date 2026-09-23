from pydantic import BaseModel
from typing import Optional


class CampaignCreate(BaseModel):
    name: str
    wordpress_site_id: int
    is_active: Optional[bool] = True


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    wordpress_site_id: Optional[int] = None
    is_active: Optional[bool] = None


class CampaignResponse(BaseModel):
    id: int
    name: str
    wordpress_site_id: int
    is_active: bool

    class Config:
        from_attributes = True

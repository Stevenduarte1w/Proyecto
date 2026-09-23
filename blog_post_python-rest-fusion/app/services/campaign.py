from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.campaign import Campaign
from app.schemas.campaign import CampaignCreate, CampaignResponse, CampaignUpdate


class CampaignService:
    """Service for managing campaigns"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_campaign(self, campaign_data: CampaignCreate) -> CampaignResponse:
        """Create a new campaign"""
        campaign = Campaign(**campaign_data.model_dump())
        self.db.add(campaign)
        self.db.commit()
        self.db.refresh(campaign)
        return CampaignResponse.model_validate(campaign)

    def get_campaign(self, campaign_id: int) -> Optional[CampaignResponse]:
        """Get a campaign by ID"""
        query = self.db.query(Campaign).filter(Campaign.id == campaign_id)
        campaign = query.first()
        if not campaign:
            return None
        return CampaignResponse.model_validate(campaign)

    def get_campaign_by_name(self, name: str) -> Optional[CampaignResponse]:
        """Get a campaign by name"""

        query = self.db.query(Campaign).filter(Campaign.name == name)
        campaign = query.first()
        if not campaign:
            return None
        return CampaignResponse.model_validate(campaign)

    def get_all_campaigns(self) -> List[CampaignResponse]:
        """Get all campaigns"""
        campaigns = self.db.query(Campaign).all()
        return [CampaignResponse.model_validate(c) for c in campaigns]

    def update_campaign(
        self, campaign_id: int, campaign_data: CampaignUpdate
    ) -> Optional[CampaignResponse]:
        """Update an existing campaign"""
        query = self.db.query(Campaign).filter(Campaign.id == campaign_id)
        campaign = query.first()
        if not campaign:
            return None

        for key, value in campaign_data.model_dump(exclude_unset=True).items():
            setattr(campaign, key, value)

        campaign.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(campaign)
        return CampaignResponse.model_validate(campaign)

    def activate_campaign(self, campaign_id: int) -> Optional[CampaignResponse]:
        """Activate a campaign"""
        query = self.db.query(Campaign).filter(Campaign.id == campaign_id)
        campaign = query.first()
        if not campaign:
            return None

        campaign.is_active = True
        campaign.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(campaign)
        return CampaignResponse.model_validate(campaign)

    def deactivate_campaign(self, campaign_id: int) -> Optional[CampaignResponse]:
        """Deactivate a campaign"""
        query = self.db.query(Campaign).filter(Campaign.id == campaign_id)
        campaign = query.first()
        if not campaign:
            return None

        campaign.is_active = False
        campaign.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(campaign)
        return CampaignResponse.model_validate(campaign)

    def delete_campaign(self, campaign_id: int) -> bool:
        """Delete a campaign"""
        query = self.db.query(Campaign).filter(Campaign.id == campaign_id)
        campaign = query.first()
        if not campaign:
            return False

        self.db.delete(campaign)
        self.db.commit()
        return True

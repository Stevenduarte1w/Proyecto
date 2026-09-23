from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, DateTime
from datetime import datetime

Base = declarative_base()


class ModelBase(Base):
    """Base model"""

    __abstract__ = True

    # Timestamps
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, onupdate=datetime.now)

    def __repr__(self):
        """String representation of the model"""
        return f"<{self.__class__.__name__} id={self.id}>"

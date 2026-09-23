from __future__ import annotations

from config.settings import settings


def get_schedule_config() -> dict:
    from config.database import SessionLocal
    from app.models.schedule_config import ScheduleConfig

    db = SessionLocal()
    try:
        row = db.query(ScheduleConfig).filter(ScheduleConfig.id == 1).first()
        if row is None:
            row = ScheduleConfig(id=1, hour="02:00", timezone=settings.SCHEDULER_TIMEZONE,
                                 enabled=settings.SCHEDULER_ENABLED)
            db.add(row)
            db.commit()
            db.refresh(row)
        return {"hour": row.hour, "timezone": row.timezone, "enabled": row.enabled}
    finally:
        db.close()


def get_scheduled_hour() -> str:
    return get_schedule_config()["hour"]


def set_scheduled_hour(new_hour: str, *, timezone: str | None = None,
                       enabled: bool | None = None) -> None:
    from config.database import SessionLocal
    from app.models.schedule_config import ScheduleConfig

    db = SessionLocal()
    try:
        row = db.query(ScheduleConfig).filter(ScheduleConfig.id == 1).first()
        if row is None:
            row = ScheduleConfig(id=1, hour=new_hour,
                                 timezone=timezone or settings.SCHEDULER_TIMEZONE,
                                 enabled=settings.SCHEDULER_ENABLED if enabled is None else enabled)
            db.add(row)
        else:
            row.hour = new_hour
            if timezone:
                row.timezone = timezone
            if enabled is not None:
                row.enabled = enabled
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

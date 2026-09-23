"""Seed sites without putting WordPress passwords in source code or the database.

Set SEED_SITES to a JSON array. Each item must contain name, url, username and
credential_ref; the named environment variable must contain a fresh Application
Password. Example shape (no secrets):
[{"name":"Example","url":"https://example.com","username":"bot",
  "credential_ref":"WP_SITE_1_APP_PASSWORD"}]
"""

import json
import os

from app.models.campaign import Campaign
from app.models.wordpress_site import WordPressSite
from config.database import SessionLocal


def run_seed() -> None:
    raw_sites = os.getenv("SEED_SITES", "[]")
    sites = json.loads(raw_sites)
    if not sites:
        raise RuntimeError("Configura SEED_SITES con los sitios a registrar.")
    db = SessionLocal()
    try:
        for config in sites:
            for field in ("name", "url", "username", "credential_ref"):
                if not config.get(field):
                    raise ValueError(f"Falta {field} en un elemento de SEED_SITES")
            if not os.getenv(config["credential_ref"]):
                raise ValueError(f"Falta la variable de entorno {config['credential_ref']}")
            site = db.query(WordPressSite).filter_by(name=config["name"]).first()
            if site is None:
                site = WordPressSite(
                    name=config["name"], url=config["url"], username=config["username"],
                    credential_ref=config["credential_ref"],
                    yoast_enabled=bool(config.get("yoast_enabled", True)),
                )
                db.add(site)
                db.flush()
            campaign_name = config.get("campaign_name", config["name"])
            campaign = db.query(Campaign).filter_by(name=campaign_name).first()
            if campaign is None:
                db.add(Campaign(name=campaign_name, wordpress_site_id=site.id, is_active=True))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
    print("Seed completed")

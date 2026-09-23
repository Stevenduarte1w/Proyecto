#!/usr/bin/env python3
"""Genera los secretos locales de la integracion Instagram <-> RPA Orchestrator.

El script no guarda nada: imprime las lineas exactas que hay que pegar en el
`.env` de cada aplicacion. Ver docs/instagram-auth-setup.md.
"""

from __future__ import annotations

import json
import secrets

BOT_KEY = "instagram-backend-01"


def main() -> None:
    bot_token = secrets.token_urlsafe(48)
    catalog_token = secrets.token_urlsafe(48)
    bot_tokens = json.dumps({bot_token: BOT_KEY}, separators=(",", ":"))

    print("\n=== Secretos de la integracion Instagram ===\n")
    print("1) .env del RPA Orchestrator")
    print(f"BOT_TOKENS={bot_tokens}")
    print(f"INSTAGRAM_BACKEND_TOKEN={catalog_token}")
    print("\n2) .env del backend Django")
    print(f"ORCHESTRATOR_BOT_TOKEN={bot_token}")
    print(f"ORCHESTRATOR_BOT_KEY={BOT_KEY}")
    print(f"INSTAGRAM_ORCHESTRATOR_TOKEN={catalog_token}")
    print("\nContrato:")
    print("  Django -> Orchestrator: ORCHESTRATOR_BOT_TOKEN == clave en BOT_TOKENS")
    print("  Orchestrator -> Django: INSTAGRAM_BACKEND_TOKEN == INSTAGRAM_ORCHESTRATOR_TOKEN")
    print("\nAviso: BOT_TOKENS es un JSON con TODOS los workers. Si el .env ya tiene")
    print("otros bots (por ejemplo saaf-backlinks-01), agrega la entrada nueva al")
    print("JSON existente en vez de reemplazarlo.\n")


if __name__ == "__main__":
    main()

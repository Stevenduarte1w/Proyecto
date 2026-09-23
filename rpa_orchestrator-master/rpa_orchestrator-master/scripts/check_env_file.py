#!/usr/bin/env python3
"""Valida un archivo .env antes de levantar los contenedores.

Corre en el pipeline justo despues de copiar la credencial, para que un valor
malformado falle en segundos con un mensaje claro en vez de hacerlo al arrancar
alembic con un traceback de pydantic-settings.

Nunca imprime secretos: de BOT_TOKENS solo muestra los bot_key y la longitud
de cada token.

Uso:
    python3 scripts/check_env_file.py [ruta-al-.env]
"""

from __future__ import annotations

import json
import re
import sys

# Settings las parsea como JSON, asi que un valor malformado rompe el arranque.
JSON_OBJECT_VARS = ("BOT_TOKENS",)


def describe(tail: str) -> str:
    """Clasifica lo que sobra sin reproducirlo: puede contener un token."""
    stripped = tail.lstrip()
    if stripped.startswith("{"):
        return "empieza otro objeto JSON (se pegaron dos en vez de fusionarlos)"
    if stripped.startswith("#"):
        return "un comentario al final de la linea"
    if stripped.startswith(("'", '"')):
        return "una comilla de cierre sobrante"
    return "texto suelto"


def read_assignments(path: str, name: str) -> list[tuple[int, str]]:
    """Devuelve (numero de linea, valor) por cada asignacion de `name`.

    Acepta espacios alrededor del '=': tanto docker compose como python-dotenv
    los recortan, asi que ignorarlos haria que el chequeo pasara de largo.
    """
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*=\s*(?P<value>.*)$")
    found = []
    with open(path, encoding="utf-8-sig") as handle:
        for number, line in enumerate(handle, 1):
            match = pattern.match(line.rstrip("\r\n"))
            if match is not None:
                found.append((number, match.group("value")))
    return found


def check_json_object(path: str, name: str) -> tuple[list[str], list[str]]:
    """Devuelve (errores, avisos) para una variable que debe ser un objeto JSON."""
    errors: list[str] = []
    warnings: list[str] = []

    assignments = read_assignments(path, name)
    if not assignments:
        print(f"{name}: no esta definido, se usara el valor por defecto")
        return errors, warnings

    if len(assignments) > 1:
        numbers = ", ".join(str(number) for number, _ in assignments)
        warnings.append(
            f"{name} esta definido {len(assignments)} veces (lineas {numbers}); "
            "gana el ultimo, pero conviene dejar uno solo"
        )

    number, value = assignments[-1]
    if not value:
        return errors, warnings

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        errors.append(
            f"{name} (linea {number}) no es JSON valido: {exc.msg} "
            f"en el caracter {exc.pos} de {len(value)}"
        )
        head, tail = value[: exc.pos], value[exc.pos :]
        if exc.msg == "Extra data":
            errors.append(
                f"  sobran {len(tail)} caracteres despues de un objeto completo:"
                f" {describe(tail)}"
            )
            try:
                valid = json.loads(head)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(valid, dict):
                    keys = ", ".join(sorted(map(str, valid.values())))
                    errors.append(f"  la parte valida solo mapea: {keys}")
        errors.append(
            "  todas las entradas van dentro del mismo objeto: "
            f'{name}={{"token-a":"bot-key-a","token-b":"bot-key-b"}}'
        )
        return errors, warnings

    if not isinstance(parsed, dict):
        errors.append(
            f"{name} (linea {number}) debe ser un objeto JSON, no {type(parsed).__name__}"
        )
        return errors, warnings

    print(f"{name}: {len(parsed)} entradas")
    for token, bot_key in sorted(parsed.items(), key=lambda item: str(item[1])):
        print(f"  {bot_key:<24} token de {len(token)} chars")
    return errors, warnings


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else ".env"
    errors: list[str] = []
    warnings: list[str] = []
    try:
        for name in JSON_OBJECT_VARS:
            found_errors, found_warnings = check_json_object(path, name)
            errors.extend(found_errors)
            warnings.extend(found_warnings)
    except OSError as exc:
        print(f"No se pudo leer {path}: {exc}", file=sys.stderr)
        return 1

    for warning in warnings:
        print(f"AVISO: {warning}")

    if errors:
        print("", file=sys.stderr)
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"{path}: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

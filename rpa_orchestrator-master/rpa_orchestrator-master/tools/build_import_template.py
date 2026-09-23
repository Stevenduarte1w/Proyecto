"""Regenerate the XLSX import template tracked at the repository root."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from orchestrator.application.import_template import (  # noqa: E402
    IMPORT_TEMPLATE_FILENAME,
    build_import_template,
)


def main() -> None:
    target = pathlib.Path(__file__).resolve().parents[1] / IMPORT_TEMPLATE_FILENAME
    target.write_bytes(build_import_template())
    print(f"wrote {target}")


if __name__ == "__main__":
    main()

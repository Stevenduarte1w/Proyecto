from __future__ import annotations

import base64
from pathlib import Path

from starlette.routing import Mount

from orchestrator.main import (
    _find_frontend_directory,
    _is_bot_write_path,
    _valid_basic_auth,
    create_app,
)


def test_dashboard_is_mounted() -> None:
    app = create_app()

    assert any(
        isinstance(route, Mount) and route.path == "/dashboard"
        for route in app.routes
    )


def test_frontend_directory_is_resolved_from_project_root() -> None:
    directory = _find_frontend_directory()

    assert directory is not None
    assert (directory / "index.html").is_file()


def test_dashboard_bootstrap_loads_core_and_instagram_modules() -> None:
    root = Path(__file__).resolve().parents[2]
    bootstrap_source = (root / "frontend" / "app.js").read_text(encoding="utf-8")
    html_source = (root / "frontend" / "index.html").read_text(encoding="utf-8")

    assert 'src="/dashboard/app.js"' in html_source
    assert 'import("/dashboard/app.core.js")' in bootstrap_source
    assert 'import("/dashboard/instagram.js")' in bootstrap_source
    assert (root / "frontend" / "app.core.js").is_file()
    assert (root / "frontend" / "instagram.js").is_file()


def test_instagram_extension_is_isolated_from_the_seo_panel() -> None:
    root = Path(__file__).resolve().parents[2]
    instagram_source = (root / "frontend" / "instagram.js").read_text(encoding="utf-8")

    # La extension solo consulta endpoints de Instagram para listar e inspeccionar.
    assert '"/instagram/executions?limit=50"' in instagram_source
    assert "/instagram/executions/" in instagram_source
    assert '"/instagram/catalog"' in instagram_source
    # Y no deja el polling corriendo cuando la pestana no esta visible.
    assert "if (!isViewActive()) return;" in instagram_source


def test_dashboard_uses_campaign_filter_and_has_no_html_preview() -> None:
    root = Path(__file__).resolve().parents[2]
    app_source = (root / "frontend" / "app.core.js").read_text(encoding="utf-8")
    html_source = (root / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "campaign_id" in app_source
    assert "global-campaign" in html_source
    assert "html_preview" not in app_source
    assert "html-preview" not in html_source


def test_dashboard_keeps_original_form_and_renders_dynamic_mongo_json() -> None:
    root = Path(__file__).resolve().parents[2]
    app_source = (root / "frontend" / "app.core.js").read_text(encoding="utf-8")
    html_source = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    css_source = (root / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'class="form-panel"' in html_source
    assert 'class="toggle-option' in html_source
    assert 'id="artifact-rendered"' in html_source
    assert "DOCUMENTO MONGODB" in html_source
    assert "renderDynamicJson" in app_source
    assert "renderPageSpeedResult" in app_source
    assert "getPageSpeedData" in app_source
    assert "profile.scores?.performance" in app_source
    assert "profile.performance," in app_source
    assert "pagespeed-report" in css_source
    assert "pagespeed-highlights" in css_source


def test_dashboard_shows_registered_page_position_from_brightlocal() -> None:
    root = Path(__file__).resolve().parents[2]
    app_source = (root / "frontend" / "app.core.js").read_text(encoding="utf-8")

    assert 'class="button position check-position"' in app_source
    assert "/rank-position" in app_source
    assert "Posición:" in app_source
    assert "Fuera del top" in app_source
    assert "consume un crédito del proveedor de búsqueda" in app_source


def test_dashboard_has_independent_post_monitor_view() -> None:
    root = Path(__file__).resolve().parents[2]
    app_source = (root / "frontend" / "app.core.js").read_text(encoding="utf-8")
    html_source = (root / "frontend" / "index.html").read_text(encoding="utf-8")

    assert 'data-view="post-monitor"' in html_source
    assert 'id="view-post-monitor"' in html_source
    assert 'id="post-alerts-body"' in html_source
    assert 'id="post-runs-body"' in html_source
    assert 'api("/post-monitor/overview")' in app_source
    assert "post_monitor" not in html_source


def test_dashboard_disables_page_execution_when_queue_is_active() -> None:
    root = Path(__file__).resolve().parents[2]
    app_source = (root / "frontend" / "app.core.js").read_text(encoding="utf-8")

    assert "hasActiveExecution = Number(page.active_queue_count || 0) > 0" in app_source
    assert 'hasActiveExecution ? "Ejecución activa" : "Ejecutar"' in app_source


def test_dashboard_basic_auth_uses_exact_credentials() -> None:
    token = base64.b64encode(b"admin:secret").decode("ascii")

    assert _valid_basic_auth(f"Basic {token}", "admin", "secret")
    assert not _valid_basic_auth(f"Basic {token}", "admin", "different")


def test_page_flow_log_and_artifact_writes_are_identified() -> None:
    assert _is_bot_write_path(
        "PUT",
        "/api/v1/page-executions/302/artifacts/result.json",
    )
    assert _is_bot_write_path("PUT", "/api/v1/page-executions/302/log")
    assert not _is_bot_write_path("GET", "/api/v1/page-executions/302/log")

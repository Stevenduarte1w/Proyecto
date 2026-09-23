# ruff: noqa: S608
from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from orchestrator.infrastructure.seo_agent.client import get_seo_agent_engine

_ADMIN_TABLES = {
    "campaigns": {
        "table": "campaigns",
        "columns": (
            "name",
            "slug",
            "domain",
            "business_name",
            "industry",
            "language",
            "main_city",
            "main_state",
            "country",
            "phone",
            "whatsapp",
            "address",
            "business_hours_text",
            "google_maps_url",
            "is_24_hours",
            "contact_page_url",
            "contact_page_wp_page_id",
            "years_experience",
            "experience_text",
            "brand_phrase",
            "brand_phrase_exact",
            "brand_phrase_allow_city_variant",
            "brand_phrase_max_uses",
            "city_links_csv_path",
            "button_style_json",
            "layout_id",
            "layout_branch",
            "youtube_channel_id",
            "default_elementor_form_id",
            "active",
        ),
        "json_columns": frozenset({"button_style_json"}),
        "select_sql": """
            SELECT *
            FROM campaigns
            ORDER BY id DESC
            LIMIT 500
        """,
    },
    "campaign-services": {
        "table": "campaign_services",
        "columns": (
            "campaign_id",
            "name",
            "slug",
            "primary_keyword",
            "category",
            "brand_phrase",
            "customer_segment",
            "language",
            "active",
            "image_policy",
            "manual_image_url",
            "image_prompt_hint",
        ),
        "json_columns": frozenset(),
        "select_sql": """
            SELECT s.*, c.name AS campaign_name, c.slug AS campaign_slug
            FROM campaign_services AS s
            JOIN campaigns AS c ON c.id = s.campaign_id
            ORDER BY s.id DESC
            LIMIT 500
        """,
    },
    "wordpress-sites": {
        "table": "wordpress_sites",
        "columns": (
            "campaign_id",
            "wp_base_url",
            "wp_api_base_url",
            "wp_admin_url",
            "auth_type",
            "username",
            "credential_ref",
            "rest_namespace",
            "elementor_enabled",
            "yoast_enabled",
            "custom_elementor_cache_enabled",
            "automation_key_ref",
            "active",
        ),
        "json_columns": frozenset(),
        "select_sql": """
            SELECT w.*, c.name AS campaign_name, c.slug AS campaign_slug
            FROM wordpress_sites AS w
            JOIN campaigns AS c ON c.id = w.campaign_id
            ORDER BY w.id DESC
            LIMIT 500
        """,
    },
    "campaign-prompt-rules": {
        "table": "campaign_prompt_rules",
        "columns": (
            "campaign_id",
            "page_type",
            "service_id",
            "rules_json",
            "active",
        ),
        "json_columns": frozenset({"rules_json"}),
        "select_sql": """
            SELECT
                r.*,
                c.name AS campaign_name,
                c.slug AS campaign_slug,
                s.name AS service_name,
                s.slug AS service_slug
            FROM campaign_prompt_rules AS r
            JOIN campaigns AS c ON c.id = r.campaign_id
            LEFT JOIN campaign_services AS s ON s.id = r.service_id
            ORDER BY r.id DESC
            LIMIT 500
        """,
    },
}


class SqlAlchemySeoAgentManagementRepository:
    async def list_campaigns(self) -> list[dict[str, Any]]:
        statement = text(
            """
            SELECT
                id,
                name,
                slug,
                domain,
                business_name,
                COALESCE(
                    NULLIF(name, ''),
                    NULLIF(business_name, ''),
                    NULLIF(slug, ''),
                    'Campaña ' || id::text
                ) AS display_name
            FROM campaigns
            ORDER BY display_name ASC, id ASC
            """
        )
        return await self._fetch_all(statement)

    async def list_admin_records(self, resource: str) -> list[dict[str, Any]]:
        config = _admin_config(resource)
        return await self._fetch_all(text(str(config["select_sql"])))

    async def create_admin_record(
        self,
        resource: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        config = _admin_config(resource)
        fields, params = _admin_payload(config, payload)
        if not fields:
            raise ValueError("At least one field is required")

        table = str(config["table"])
        columns_sql = ", ".join(fields)
        values_sql = ", ".join(_admin_value_sql(config, field) for field in fields)
        statement = text(  # noqa: S608 - table and columns come from _ADMIN_TABLES.
            f"""
            INSERT INTO {table} ({columns_sql})
            VALUES ({values_sql})
            RETURNING *
            """
        )
        try:
            async with get_seo_agent_engine().begin() as connection:
                result = await connection.execute(statement, params)
                return dict(result.mappings().one())
        except IntegrityError as exc:
            raise ValueError(str(exc.orig)) from exc

    async def update_admin_record(
        self,
        resource: str,
        record_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        config = _admin_config(resource)
        fields, params = _admin_payload(config, payload)
        if not fields:
            raise ValueError("At least one field is required")

        table = str(config["table"])
        params["id"] = record_id
        set_parts = [
            f"{field} = {_admin_value_sql(config, field)}" for field in fields
        ]
        if "updated_at" in set(_table_columns(config)):
            set_parts.append("updated_at = NOW()")
        set_sql = ", ".join(set_parts)
        statement = text(  # noqa: S608 - table and columns come from _ADMIN_TABLES.
            f"""
            UPDATE {table}
            SET {set_sql}
            WHERE id = :id
            RETURNING *
            """
        )
        try:
            async with get_seo_agent_engine().begin() as connection:
                result = await connection.execute(statement, params)
                row = result.mappings().one_or_none()
        except IntegrityError as exc:
            raise ValueError(str(exc.orig)) from exc
        if row is None:
            raise LookupError(f"{resource} record {record_id} was not found")
        return dict(row)

    async def delete_admin_record(self, resource: str, record_id: int) -> dict[str, Any]:
        config = _admin_config(resource)
        table = str(config["table"])
        statement = text(  # noqa: S608 - table comes from _ADMIN_TABLES.
            f"""
            DELETE FROM {table}
            WHERE id = :id
            RETURNING *
            """
        )
        try:
            async with get_seo_agent_engine().begin() as connection:
                result = await connection.execute(statement, {"id": record_id})
                row = result.mappings().one_or_none()
        except IntegrityError as exc:
            raise ValueError(str(exc.orig)) from exc
        if row is None:
            raise LookupError(f"{resource} record {record_id} was not found")
        return dict(row)

    async def list_services(
        self,
        campaign_id: int | None = None,
        campaign_slug: str | None = None,
    ) -> list[dict[str, Any]]:
        if campaign_id is None and not campaign_slug:
            return []

        statement = text(
            """
            SELECT
                s.id,
                s.campaign_id,
                s.name,
                s.slug,
                s.primary_keyword,
                s.category
            FROM campaign_services AS s
            JOIN campaigns AS c ON c.id = s.campaign_id
            WHERE s.active = TRUE
              AND (
                  CAST(:campaign_id AS INTEGER) IS NULL
                  OR s.campaign_id = CAST(:campaign_id AS INTEGER)
              )
              AND (
                  CAST(:campaign_slug AS TEXT) IS NULL
                  OR c.slug = CAST(:campaign_slug AS TEXT)
              )
            ORDER BY s.name ASC
            """
        )
        return await self._fetch_all(
            statement,
            {
                "campaign_id": campaign_id,
                "campaign_slug": campaign_slug or None,
            },
        )

    async def list_pages(
        self,
        *,
        campaign_id: int | None = None,
        campaign_slug: str | None = None,
        page_type: str | None = None,
        limit: int = 300,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "campaign_id": campaign_id,
            "campaign_slug": campaign_slug or None,
            "page_type": page_type or None,
            "limit": min(max(limit, 1), 1000),
            "offset": max(offset, 0),
        }

        statement = text(
            """
            SELECT
                cp.*,
                c.name AS campaign_name,
                c.slug AS campaign_slug,
                c.domain AS campaign_domain,
                c.business_name AS campaign_business_name,
                s.name AS service_name,
                s.slug AS service_slug,
                q.id AS last_queue_id,
                q.status AS last_queue_status,
                q.result_status AS last_result_status,
                q.finished_at AS last_finished_at,
                q.error_message AS last_error_message,
                COALESCE(q_failed.failed_count, 0) AS failed_count,
                COALESCE(q_active.active_count, 0) AS active_queue_count,
                CASE
                    WHEN q.status = 'running' THEN 'running'
                    WHEN q.status = 'queued' THEN 'queued'
                    WHEN cp.status = 'published' THEN 'published'
                    WHEN q.status = 'success'
                         AND COALESCE(q.result_status, '') IN
                             ('published', 'success', 'ok', 'completed', '')
                        THEN 'published'
                    WHEN q.status = 'success' THEN 'success'
                    WHEN q.status = 'failed' THEN 'failed'
                    WHEN q.status = 'cancelled' THEN 'cancelled'
                    ELSE cp.status
                END AS page_display_status
            FROM campaign_pages AS cp
            JOIN campaigns AS c ON c.id = cp.campaign_id
            LEFT JOIN campaign_services AS s ON s.id = cp.service_id
            LEFT JOIN LATERAL (
                SELECT id, status, result_status, finished_at, error_message
                FROM page_execution_queue
                WHERE campaign_page_id = cp.id
                ORDER BY id DESC
                LIMIT 1
            ) AS q ON TRUE
            LEFT JOIN LATERAL (
                SELECT COUNT(*)::int AS failed_count
                FROM page_execution_queue
                WHERE campaign_page_id = cp.id AND status = 'failed'
            ) AS q_failed ON TRUE
            LEFT JOIN LATERAL (
                SELECT COUNT(*)::int AS active_count
                FROM page_execution_queue
                WHERE campaign_page_id = cp.id AND status IN ('queued', 'running')
            ) AS q_active ON TRUE
            WHERE (
                CAST(:campaign_id AS INTEGER) IS NULL
                OR cp.campaign_id = CAST(:campaign_id AS INTEGER)
            )
              AND (
                  CAST(:campaign_slug AS TEXT) IS NULL
                  OR c.slug = CAST(:campaign_slug AS TEXT)
              )
              AND (
                  CAST(:page_type AS TEXT) IS NULL
                  OR cp.page_type = CAST(:page_type AS TEXT)
              )
            ORDER BY cp.id DESC
            LIMIT CAST(:limit AS INTEGER)
            OFFSET CAST(:offset AS INTEGER)
            """
        )
        return await self._fetch_all(statement, params)

    async def create_page(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with get_seo_agent_engine().begin() as connection:
            campaign = (
                await connection.execute(
                    text("SELECT id FROM campaigns WHERE id = :campaign_id"),
                    {"campaign_id": payload["campaign_id"]},
                )
            ).mappings().one_or_none()
            if campaign is None:
                raise ValueError("campaign_id does not exist")

            service_id = payload.get("service_id")
            if service_id is not None:
                service = (
                    await connection.execute(
                        text(
                            """
                            SELECT id
                            FROM campaign_services
                            WHERE id = :service_id
                              AND campaign_id = :campaign_id
                              AND active = TRUE
                            """
                        ),
                        {
                            "service_id": service_id,
                            "campaign_id": payload["campaign_id"],
                        },
                    )
                ).mappings().one_or_none()
                if service is None:
                    raise ValueError(
                        "service_id does not belong to the selected campaign"
                    )

            duplicate = (
                await connection.execute(
                    text(
                        """
                        SELECT id, url, slug
                        FROM campaign_pages
                        WHERE campaign_id = :campaign_id
                          AND (url = :url OR slug = :slug)
                        LIMIT 1
                        """
                    ),
                    {
                        "campaign_id": payload["campaign_id"],
                        "url": payload["url"],
                        "slug": payload["slug"],
                    },
                )
            ).mappings().one_or_none()
            if duplicate is not None:
                raise ValueError(
                    f"A page with the same URL or slug already exists: id={duplicate['id']}"
                )

            params = dict(payload)
            params["secondary_keywords"] = json.dumps(
                payload.get("secondary_keywords", []),
                ensure_ascii=False,
            )
            await _resolve_parent_page(connection, params)
            result = await connection.execute(
                text(
                    """
                    INSERT INTO campaign_pages (
                        campaign_id, service_id, wp_page_id, url, slug, page_type,
                        language, primary_keyword, secondary_keywords, service_scope,
                        customer_segment, city, state, country, postal_code,
                        target_location_name, target_google_maps_url, location_type,
                        parent_city, delivery_mode, allows_remote, allows_onsite,
                        physical_visit_required, allow_publish, status,
                        page_template, layout_id, layout_branch,
                        parent_campaign_page_id, parent_wp_page_id, parent_slug,
                        parent_required, elementor_form_id, youtube_channel_id,
                        created_at, updated_at
                    )
                    VALUES (
                        :campaign_id, :service_id, :wp_page_id, :url, :slug, :page_type,
                        :language, :primary_keyword,
                        CAST(:secondary_keywords AS jsonb), :service_scope,
                        :customer_segment, :city, :state, :country, :postal_code,
                        :target_location_name, :target_google_maps_url, :location_type,
                        :parent_city, :delivery_mode, :allows_remote, :allows_onsite,
                        :physical_visit_required, :allow_publish, :status,
                        :page_template, :layout_id, :layout_branch,
                        :parent_campaign_page_id, :parent_wp_page_id, :parent_slug,
                        :parent_required, :elementor_form_id, :youtube_channel_id,
                        NOW(), NOW()
                    )
                    RETURNING *
                    """
                ),
                params,
            )
            row = result.mappings().one()
        return dict(row)

    async def update_page(
        self,
        campaign_page_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        unknown = sorted(set(payload).difference(_PAGE_UPDATABLE_COLUMNS))
        if unknown:
            raise ValueError(f"Unsupported fields: {', '.join(unknown)}")
        if not payload:
            raise ValueError("At least one field is required")

        params = dict(payload)
        if "secondary_keywords" in params:
            params["secondary_keywords"] = json.dumps(
                payload["secondary_keywords"] or [],
                ensure_ascii=False,
            )
        params["id"] = campaign_page_id
        async with get_seo_agent_engine().begin() as connection:
            current = (
                await connection.execute(
                    text(
                        """
                        SELECT id, campaign_id, parent_campaign_page_id
                        FROM campaign_pages
                        WHERE id = :id
                        """
                    ),
                    {"id": campaign_page_id},
                )
            ).mappings().one_or_none()
            if current is None:
                raise LookupError(f"campaign_page {campaign_page_id} was not found")

            if "parent_campaign_page_id" in params or "parent_slug" in params:
                if "parent_slug" not in params:
                    # Only the id changed: keep resolving from it.
                    params.setdefault(
                        "parent_campaign_page_id",
                        current["parent_campaign_page_id"],
                    )
                params["campaign_id"] = int(current["campaign_id"])
                await _resolve_parent_page(connection, params, page_id=campaign_page_id)
                params.pop("campaign_id", None)

            fields = [field for field in _PAGE_UPDATE_ORDER if field in params]
            set_sql = ", ".join(
                f"{field} = {_page_value_sql(field)}" for field in fields
            )
            try:
                result = await connection.execute(
                    text(  # noqa: S608 - fields validated against _PAGE_UPDATABLE_COLUMNS.
                        f"""
                        UPDATE campaign_pages
                        SET {set_sql}, updated_at = NOW()
                        WHERE id = :id
                        RETURNING *
                        """
                    ),
                    params,
                )
                row = result.mappings().one()
            except IntegrityError as exc:
                raise ValueError(str(exc.orig)) from exc
        return dict(row)

    async def upsert_import_page(
        self,
        payload: dict[str, Any],
        campaign_page_id: int | None,
        dry_run: bool,
    ) -> tuple[dict[str, Any], str]:
        async with get_seo_agent_engine().begin() as connection:
            existing = None
            if campaign_page_id is not None:
                existing = (
                    await connection.execute(
                        text(
                            """
                            SELECT *
                            FROM campaign_pages
                            WHERE id = :page_id AND campaign_id = :campaign_id
                            """
                        ),
                        {
                            "page_id": campaign_page_id,
                            "campaign_id": payload["campaign_id"],
                        },
                    )
                ).mappings().one_or_none()
            if existing is None:
                existing = (
                    await connection.execute(
                        text(
                            """
                            SELECT *
                            FROM campaign_pages
                            WHERE campaign_id = :campaign_id
                              AND (
                                (
                                    CAST(:wp_page_id AS INTEGER) IS NOT NULL
                                    AND wp_page_id = CAST(:wp_page_id AS INTEGER)
                                )
                                OR url = :url
                              )
                            ORDER BY id DESC
                            LIMIT 1
                            """
                        ),
                        {
                            "campaign_id": payload["campaign_id"],
                            "wp_page_id": payload.get("wp_page_id"),
                            "url": payload["url"],
                            "slug": payload["slug"],
                        },
                    )
                ).mappings().one_or_none()

            action = "updated" if existing is not None else "created"
            if dry_run:
                preview = dict(existing) if existing is not None else dict(payload)
                preview.setdefault("id", None)
                return preview, f"would_{action[:-1] if action.endswith('d') else action}"

            params = dict(payload)
            params["secondary_keywords"] = json.dumps(
                payload.get("secondary_keywords", []),
                ensure_ascii=False,
            )
            await _resolve_parent_page(
                connection,
                params,
                page_id=int(existing["id"]) if existing is not None else None,
            )
            if existing is not None:
                params["id"] = existing["id"]
                result = await connection.execute(
                    text(
                        """
                        UPDATE campaign_pages
                        SET
                            service_id = :service_id,
                            wp_page_id = COALESCE(:wp_page_id, wp_page_id),
                            url = :url,
                            slug = :slug,
                            page_type = :page_type,
                            language = :language,
                            primary_keyword = :primary_keyword,
                            secondary_keywords = CAST(:secondary_keywords AS jsonb),
                            service_scope = :service_scope,
                            customer_segment = :customer_segment,
                            city = :city,
                            state = :state,
                            country = :country,
                            target_location_name = :target_location_name,
                            target_google_maps_url = :target_google_maps_url,
                            location_type = :location_type,
                            parent_city = :parent_city,
                            delivery_mode = :delivery_mode,
                            allows_remote = COALESCE(:allows_remote, allows_remote),
                            allows_onsite = COALESCE(:allows_onsite, allows_onsite),
                            physical_visit_required = COALESCE(
                                :physical_visit_required,
                                physical_visit_required
                            ),
                            allow_publish = COALESCE(:allow_publish, allow_publish),
                            status = :status,
                            postal_code = COALESCE(:postal_code, postal_code),
                            page_template = COALESCE(
                                :page_template,
                                page_template
                            ),
                            layout_id = COALESCE(:layout_id, layout_id),
                            layout_branch = COALESCE(:layout_branch, layout_branch),
                            parent_campaign_page_id = COALESCE(
                                :parent_campaign_page_id,
                                parent_campaign_page_id
                            ),
                            parent_wp_page_id = COALESCE(
                                :parent_wp_page_id,
                                parent_wp_page_id
                            ),
                            parent_slug = COALESCE(:parent_slug, parent_slug),
                            parent_required = COALESCE(
                                :parent_required,
                                parent_required
                            ),
                            elementor_form_id = COALESCE(
                                :elementor_form_id,
                                elementor_form_id
                            ),
                            youtube_channel_id = COALESCE(
                                :youtube_channel_id,
                                youtube_channel_id
                            ),
                            updated_at = NOW()
                        WHERE id = :id
                        RETURNING *
                        """
                    ),
                    params,
                )
            else:
                result = await connection.execute(
                    text(
                        """
                        INSERT INTO campaign_pages (
                            campaign_id, service_id, wp_page_id, url, slug, page_type,
                            language, primary_keyword, secondary_keywords, service_scope,
                            customer_segment, city, state, country, postal_code,
                            target_location_name, target_google_maps_url, location_type,
                            parent_city, delivery_mode, allows_remote, allows_onsite,
                            physical_visit_required, allow_publish, status,
                            page_template, layout_id, layout_branch,
                            parent_campaign_page_id, parent_wp_page_id, parent_slug,
                            parent_required, elementor_form_id, youtube_channel_id,
                            created_at, updated_at
                        )
                        VALUES (
                            :campaign_id, :service_id, :wp_page_id, :url, :slug,
                            :page_type, :language, :primary_keyword,
                            CAST(:secondary_keywords AS jsonb), :service_scope,
                            :customer_segment, :city, :state, :country, :postal_code,
                            :target_location_name, :target_google_maps_url,
                            :location_type, :parent_city, :delivery_mode,
                            :allows_remote, :allows_onsite, :physical_visit_required,
                            :allow_publish, :status,
                            :page_template, :layout_id, :layout_branch,
                            :parent_campaign_page_id, :parent_wp_page_id, :parent_slug,
                            :parent_required, :elementor_form_id, :youtube_channel_id,
                            NOW(), NOW()
                        )
                        RETURNING *
                        """
                    ),
                    params,
                )
            return dict(result.mappings().one()), action

    async def schedule_pages(
        self,
        campaign_page_ids: list[int],
        scheduled_for: date,
        notes: str,
        priority: int = 100,
    ) -> dict[str, Any]:
        inserted: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        async with get_seo_agent_engine().begin() as connection:
            for page_id in campaign_page_ids:
                page = (
                    await connection.execute(
                        text("SELECT id, campaign_id FROM campaign_pages WHERE id = :page_id"),
                        {"page_id": page_id},
                    )
                ).mappings().one_or_none()
                if page is None:
                    skipped.append(
                        {"campaign_page_id": page_id, "reason": "page_not_found"}
                    )
                    continue

                duplicate = (
                    await connection.execute(
                        text(
                            """
                            SELECT id, status
                            FROM page_execution_queue
                            WHERE campaign_page_id = :page_id
                              AND trigger_type = 'daily_auto'
                              AND scheduled_for = :scheduled_for
                              AND status IN ('queued', 'running', 'success')
                            ORDER BY id DESC
                            LIMIT 1
                            """
                        ),
                        {"page_id": page_id, "scheduled_for": scheduled_for},
                    )
                ).mappings().one_or_none()
                if duplicate is not None:
                    skipped.append(
                        {
                            "campaign_page_id": page_id,
                            "existing_queue_id": duplicate["id"],
                            "reason": "duplicate_schedule",
                        }
                    )
                    continue

                result = await connection.execute(
                    text(
                        """
                        INSERT INTO page_execution_queue (
                            campaign_page_id, trigger_type, status, priority,
                            scheduled_for, notes, created_at, updated_at
                        )
                        VALUES (
                            :page_id, 'daily_auto', 'queued', :priority,
                            :scheduled_for, :notes, NOW(), NOW()
                        )
                        RETURNING id, campaign_page_id, trigger_type, status,
                                  scheduled_for, priority
                        """
                    ),
                    {
                        "page_id": page_id,
                        "scheduled_for": scheduled_for,
                        "notes": notes,
                        "priority": priority,
                    },
                )
                inserted_row = dict(result.mappings().one())
                inserted_row["campaign_id"] = int(page["campaign_id"])
                inserted.append(inserted_row)

        return {
            "inserted_count": len(inserted),
            "inserted": inserted,
            "skipped": skipped,
        }

    async def list_queue(
        self,
        *,
        view: str = "all",
        campaign_id: int | None = None,
        campaign_page_id: int | None = None,
        page_type: str | None = None,
        limit: int = 150,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "view": view,
            "campaign_id": campaign_id,
            "campaign_page_id": campaign_page_id,
            "page_type": page_type or None,
            "limit": min(max(limit, 1), 1000),
        }

        statement = text(
            """
            SELECT
                q.*,
                cp.campaign_id,
                cp.slug AS page_slug,
                cp.primary_keyword,
                cp.url,
                cp.page_type,
                cp.city,
                cp.state,
                cp.target_location_name,
                c.name AS campaign_name,
                c.slug AS campaign_slug,
                s.name AS service_name
            FROM page_execution_queue AS q
            JOIN campaign_pages AS cp ON cp.id = q.campaign_page_id
            JOIN campaigns AS c ON c.id = cp.campaign_id
            LEFT JOIN campaign_services AS s ON s.id = cp.service_id
            WHERE (
                CAST(:view AS TEXT) = 'all'
                OR (
                    CAST(:view AS TEXT) = 'active'
                    AND q.status IN ('queued', 'running')
                )
                OR (
                    CAST(:view AS TEXT) = 'history'
                    AND q.status IN ('success', 'failed', 'cancelled')
                )
            )
              AND (
                  CAST(:campaign_id AS INTEGER) IS NULL
                  OR cp.campaign_id = CAST(:campaign_id AS INTEGER)
              )
              AND (
                  CAST(:campaign_page_id AS INTEGER) IS NULL
                  OR q.campaign_page_id = CAST(:campaign_page_id AS INTEGER)
              )
              AND (
                  CAST(:page_type AS TEXT) IS NULL
                  OR cp.page_type = CAST(:page_type AS TEXT)
              )
            ORDER BY q.id DESC
            LIMIT CAST(:limit AS INTEGER)
            """
        )
        return await self._fetch_all(statement, params)

    async def create_run_now(
        self,
        campaign_page_id: int,
        notes: str,
    ) -> dict[str, Any]:
        async with get_seo_agent_engine().begin() as connection:
            page = (
                await connection.execute(
                    text("SELECT id FROM campaign_pages WHERE id = :page_id"),
                    {"page_id": campaign_page_id},
                )
            ).mappings().one_or_none()
            if page is None:
                raise ValueError("campaign_page_id does not exist")

            active = (
                await connection.execute(
                    text(
                        """
                        SELECT id, status
                        FROM page_execution_queue
                        WHERE campaign_page_id = :page_id
                          AND status IN ('queued', 'running')
                        ORDER BY id DESC
                        LIMIT 1
                        """
                    ),
                    {"page_id": campaign_page_id},
                )
            ).mappings().one_or_none()
            if active is not None:
                return {
                    "ok": False,
                    "error": "This page already has an active execution",
                    "existing_queue_id": active["id"],
                    "existing_status": active["status"],
                    "campaign_page_id": campaign_page_id,
                }

            result = await connection.execute(
                text(
                    """
                    INSERT INTO page_execution_queue (
                        campaign_page_id, trigger_type, status, priority,
                        scheduled_for, notes, created_at, updated_at
                    )
                    VALUES (
                        :page_id, 'manual', 'queued', 1,
                        CURRENT_DATE, :notes, NOW(), NOW()
                    )
                    RETURNING *
                    """
                ),
                {"page_id": campaign_page_id, "notes": notes},
            )
            row = result.mappings().one()
        return {"ok": True, "queue": dict(row)}

    async def retry_queue(self, queue_execution_id: int) -> dict[str, Any]:
        async with get_seo_agent_engine().begin() as connection:
            original = (
                await connection.execute(
                    text(
                        """
                        SELECT campaign_page_id
                        FROM page_execution_queue
                        WHERE id = :queue_id AND status IN ('failed', 'cancelled')
                        """
                    ),
                    {"queue_id": queue_execution_id},
                )
            ).mappings().one_or_none()
            if original is None:
                raise ValueError("Only failed or cancelled executions can be retried")

            page_id = int(original["campaign_page_id"])
            active = (
                await connection.execute(
                    text(
                        """
                        SELECT id, status
                        FROM page_execution_queue
                        WHERE campaign_page_id = :page_id
                          AND status IN ('queued', 'running')
                        LIMIT 1
                        """
                    ),
                    {"page_id": page_id},
                )
            ).mappings().one_or_none()
            if active is not None:
                raise ValueError(
                    f"The page already has an active execution: {active['id']}"
                )

            result = await connection.execute(
                text(
                    """
                    INSERT INTO page_execution_queue (
                        campaign_page_id, trigger_type, status, priority,
                        scheduled_for, notes, created_at, updated_at
                    )
                    VALUES (
                        :page_id, 'manual', 'queued', 1, CURRENT_DATE,
                        :notes, NOW(), NOW()
                    )
                    RETURNING *
                    """
                ),
                {
                    "page_id": page_id,
                    "notes": f"Retry of queue_id={queue_execution_id}",
                },
            )
            row = result.mappings().one()
        return {"ok": True, "queue": dict(row)}

    async def cancel_queue(self, queue_execution_id: int) -> dict[str, Any] | None:
        statement = text(
            """
            UPDATE page_execution_queue
            SET
                status = 'cancelled',
                result_status = 'cancelled_by_user',
                finished_at = NOW(),
                error_message = 'Cancelled from dashboard',
                updated_at = NOW()
            WHERE id = :queue_id AND status = 'queued'
            RETURNING *
            """
        )
        async with get_seo_agent_engine().begin() as connection:
            result = await connection.execute(
                statement,
                {"queue_id": queue_execution_id},
            )
            row = result.mappings().one_or_none()
        return dict(row) if row is not None else None

    async def list_post_groups(
        self,
        *,
        campaign_id: int | None = None,
        state: str | None = None,
        post_status: str | None = None,
        search: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        statement = text(
            """
            SELECT g.*, c.name AS campaign_name
            FROM v_support_post_groups AS g
            JOIN campaigns AS c ON c.id = g.campaign_id
            WHERE (
                CAST(:campaign_id AS INTEGER) IS NULL
                OR g.campaign_id = CAST(:campaign_id AS INTEGER)
            )
              AND (
                  CAST(:state AS TEXT) IS NULL
                  OR g.state_key = CAST(:state AS TEXT)
              )
              AND (
                  CAST(:post_status AS TEXT) IS NULL
                  OR g.post_status = CAST(:post_status AS TEXT)
              )
              AND (
                  CAST(:search AS TEXT) IS NULL
                  OR g.region_name ILIKE CAST(:search AS TEXT)
                  OR COALESCE(g.post_title, '') ILIKE CAST(:search AS TEXT)
                  OR COALESCE(g.keyphrase, '') ILIKE CAST(:search AS TEXT)
                  OR COALESCE(g.slug, '') ILIKE CAST(:search AS TEXT)
                  OR CAST(g.cities AS TEXT) ILIKE CAST(:search AS TEXT)
              )
            ORDER BY g.campaign_id ASC, g.priority ASC, g.id DESC
            LIMIT CAST(:limit AS INTEGER)
            """
        )
        return await self._fetch_all(
            statement,
            {
                "campaign_id": campaign_id,
                "state": state or None,
                "post_status": post_status or None,
                "search": f"%{search}%" if search else None,
                "limit": min(max(limit, 1), 1000),
            },
        )

    async def create_post_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        cities = list(payload.get("cities") or [])
        params = {key: value for key, value in payload.items() if key != "cities"}
        try:
            async with get_seo_agent_engine().begin() as connection:
                result = await connection.execute(
                    text(
                        """
                        INSERT INTO support_post_groups (
                            campaign_id, state, region_name, group_type,
                            priority, status, post_title, keyphrase, slug,
                            post_category, post_url, post_status,
                            created_at, updated_at
                        )
                        VALUES (
                            :campaign_id, :state, :region_name, :group_type,
                            :priority, :status, :post_title, :keyphrase, :slug,
                            :post_category, :post_url, :post_status, NOW(), NOW()
                        )
                        RETURNING id
                        """
                    ),
                    params,
                )
                group_id = int(result.scalar_one())
                await _replace_group_cities(connection, group_id, cities)
        except IntegrityError as exc:
            raise ValueError(str(exc.orig)) from exc
        return await self._get_post_group(group_id)

    async def update_post_group(
        self,
        group_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        cities = payload.get("cities")
        params = {
            key: value
            for key, value in payload.items()
            if key != "cities" and key in _POST_GROUP_UPDATABLE_COLUMNS
        }
        unknown = sorted(
            set(payload).difference(_POST_GROUP_UPDATABLE_COLUMNS).difference({"cities"})
        )
        if unknown:
            raise ValueError(f"Unsupported fields: {', '.join(unknown)}")
        try:
            async with get_seo_agent_engine().begin() as connection:
                if params:
                    fields = [
                        field for field in _POST_GROUP_UPDATE_ORDER if field in params
                    ]
                    set_sql = ", ".join(f"{field} = :{field}" for field in fields)
                    result = await connection.execute(
                        text(  # noqa: S608 - fields validated above.
                            f"""
                            UPDATE support_post_groups
                            SET {set_sql}, updated_at = NOW()
                            WHERE id = :id
                            RETURNING id
                            """
                        ),
                        {**params, "id": group_id},
                    )
                    if result.mappings().one_or_none() is None:
                        raise LookupError(f"support_post_group {group_id} was not found")
                else:
                    existing = (
                        await connection.execute(
                            text(
                                "SELECT id FROM support_post_groups WHERE id = :id"
                            ),
                            {"id": group_id},
                        )
                    ).mappings().one_or_none()
                    if existing is None:
                        raise LookupError(f"support_post_group {group_id} was not found")

                if cities is not None:
                    await _replace_group_cities(connection, group_id, cities)
        except IntegrityError as exc:
            raise ValueError(str(exc.orig)) from exc
        return await self._get_post_group(group_id)

    async def delete_post_group(self, group_id: int) -> dict[str, Any]:
        group = await self._get_post_group(group_id)
        async with get_seo_agent_engine().begin() as connection:
            await connection.execute(
                text("DELETE FROM support_post_groups WHERE id = :id"),
                {"id": group_id},
            )
        return group

    async def _get_post_group(self, group_id: int) -> dict[str, Any]:
        rows = await self._fetch_all(
            text(
                """
                SELECT g.*, c.name AS campaign_name
                FROM v_support_post_groups AS g
                JOIN campaigns AS c ON c.id = g.campaign_id
                WHERE g.id = :id
                """
            ),
            {"id": group_id},
        )
        if not rows:
            raise LookupError(f"support_post_group {group_id} was not found")
        return rows[0]

    async def get_page(self, campaign_page_id: int) -> dict[str, Any] | None:
        statement = text(
            """
            SELECT
                cp.*,
                c.name AS campaign_name,
                c.slug AS campaign_slug,
                c.domain AS campaign_domain,
                c.business_name AS campaign_business_name,
                s.name AS service_name,
                s.slug AS service_slug,
                EXISTS (
                    SELECT 1
                    FROM page_execution_queue AS completed_queue
                    WHERE completed_queue.campaign_page_id = cp.id
                      AND completed_queue.status = 'success'
                      AND COALESCE(completed_queue.result_status, '') IN
                          ('published', 'success', 'ok', 'completed', '')
                ) AS has_successful_optimization
            FROM campaign_pages AS cp
            JOIN campaigns AS c ON c.id = cp.campaign_id
            LEFT JOIN campaign_services AS s ON s.id = cp.service_id
            WHERE cp.id = :page_id
            """
        )
        rows = await self._fetch_all(statement, {"page_id": campaign_page_id})
        return rows[0] if rows else None

    async def update_page_wp_page_id(
        self,
        campaign_page_id: int,
        wp_page_id: int,
    ) -> None:
        statement = text(
            """
            UPDATE campaign_pages
            SET wp_page_id = :wp_page_id, updated_at = NOW()
            WHERE id = :page_id
            """
        )
        async with get_seo_agent_engine().begin() as connection:
            result = await connection.execute(
                statement,
                {"page_id": campaign_page_id, "wp_page_id": wp_page_id},
            )
        if result.rowcount == 0:
            raise LookupError(f"campaign_page {campaign_page_id} was not found")

    async def get_due_queue(self, limit: int) -> list[dict[str, Any]]:
        statement = text(
            """
            SELECT q.*, cp.campaign_id
            FROM page_execution_queue AS q
            JOIN campaign_pages AS cp ON cp.id = q.campaign_page_id
            WHERE q.status = 'queued'
              AND q.scheduled_for <= CURRENT_DATE
            ORDER BY q.priority ASC, q.id ASC
            LIMIT :limit
            """
        )
        return await self._fetch_all(statement, {"limit": min(max(limit, 1), 100)})

    async def mark_queue_running(self, queue_execution_id: int) -> bool:
        statement = text(
            """
            UPDATE page_execution_queue
            SET status = 'running',
                attempts = COALESCE(attempts, 0) + 1,
                started_at = COALESCE(started_at, NOW()),
                updated_at = NOW()
            WHERE id = :queue_id AND status = 'queued'
            RETURNING id
            """
        )
        async with get_seo_agent_engine().begin() as connection:
            result = await connection.execute(statement, {"queue_id": queue_execution_id})
            return result.scalar_one_or_none() is not None

    async def note_queue_start_error(
        self, queue_execution_id: int, error_message: str
    ) -> None:
        statement = text(
            """
            UPDATE page_execution_queue
            SET result_status = 'start_error',
                error_message = :error_message,
                updated_at = NOW()
            WHERE id = :queue_id AND status = 'running'
            """
        )
        async with get_seo_agent_engine().begin() as connection:
            await connection.execute(
                statement,
                {
                    "queue_id": queue_execution_id,
                    "error_message": error_message[:1000],
                },
            )

    async def update_queue_result(
        self,
        queue_execution_id: int,
        *,
        status: str,
        result_status: str,
        error_message: str | None = None,
    ) -> None:
        statement = text(
            """
            UPDATE page_execution_queue
            SET
                status = CAST(:status AS VARCHAR),
                result_status = CAST(:result_status AS VARCHAR),
                error_message = CAST(:error_message AS TEXT),
                finished_at = CASE
                    WHEN CAST(:status AS VARCHAR)
                         IN ('success', 'failed', 'cancelled') THEN NOW()
                    ELSE finished_at
                END,
                updated_at = NOW()
            WHERE id = CAST(:queue_id AS INTEGER)
            """
        )
        async with get_seo_agent_engine().begin() as connection:
            await connection.execute(
                statement,
                {
                    "queue_id": queue_execution_id,
                    "status": status,
                    "result_status": result_status,
                    "error_message": error_message,
                },
            )

    async def _fetch_all(
        self,
        statement: Any,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        async with get_seo_agent_engine().connect() as connection:
            result = await connection.execute(statement, params or {})
            return [dict(row) for row in result.mappings().all()]


_POST_GROUP_UPDATE_ORDER: tuple[str, ...] = (
    "campaign_id",
    "state",
    "region_name",
    "group_type",
    "priority",
    "status",
    "post_title",
    "keyphrase",
    "slug",
    "post_category",
    "post_url",
    "post_status",
)
_POST_GROUP_UPDATABLE_COLUMNS = frozenset(_POST_GROUP_UPDATE_ORDER)


async def _replace_group_cities(
    connection: Any,
    group_id: int,
    cities: list[dict[str, Any]],
) -> None:
    await connection.execute(
        text("DELETE FROM support_post_group_cities WHERE group_id = :group_id"),
        {"group_id": group_id},
    )
    if not cities:
        return
    # city_key and state_key are generated columns: the database derives them.
    await connection.execute(
        text(
            """
            INSERT INTO support_post_group_cities (
                group_id, city, state, created_at
            )
            VALUES (:group_id, :city, :state, NOW())
            """
        ),
        [
            {"group_id": group_id, "city": city["city"], "state": city["state"]}
            for city in cities
        ],
    )


_PAGE_UPDATE_ORDER: tuple[str, ...] = (
    "service_id",
    "wp_page_id",
    "url",
    "slug",
    "page_type",
    "language",
    "primary_keyword",
    "secondary_keywords",
    "service_scope",
    "customer_segment",
    "city",
    "state",
    "country",
    "postal_code",
    "target_location_name",
    "target_google_maps_url",
    "location_type",
    "parent_city",
    "delivery_mode",
    "allows_remote",
    "allows_onsite",
    "physical_visit_required",
    "allow_publish",
    "status",
    "page_template",
    "layout_id",
    "layout_branch",
    "parent_campaign_page_id",
    "parent_wp_page_id",
    "parent_slug",
    "parent_required",
    "elementor_form_id",
    "youtube_channel_id",
)
_PAGE_UPDATABLE_COLUMNS = frozenset(_PAGE_UPDATE_ORDER)


def _page_value_sql(field: str) -> str:
    if field == "secondary_keywords":
        return f"CAST(:{field} AS jsonb)"
    return f":{field}"


async def _resolve_parent_page(
    connection: Any,
    params: dict[str, Any],
    page_id: int | None = None,
) -> None:
    """Fill parent_wp_page_id/parent_slug from the referenced WordPress parent.

    The dashboard and the Excel import only provide ``parent_campaign_page_id``
    or ``parent_slug``; the WordPress identifier is always derived here.
    """
    params.setdefault("parent_campaign_page_id", None)
    params.setdefault("parent_slug", None)
    params.setdefault("parent_required", False)
    params["parent_wp_page_id"] = None

    parent_id = params.get("parent_campaign_page_id")
    parent_slug = str(params.get("parent_slug") or "").strip("/")
    campaign_id = params.get("campaign_id")

    if parent_id is None and parent_slug:
        found = (
            await connection.execute(
                text(
                    """
                    SELECT id
                    FROM campaign_pages
                    WHERE campaign_id = :campaign_id AND LOWER(slug) = LOWER(:slug)
                    ORDER BY id ASC
                    LIMIT 1
                    """
                ),
                {"campaign_id": campaign_id, "slug": parent_slug},
            )
        ).mappings().one_or_none()
        if found is None:
            # The parent is not registered yet: keep the slug so the WordPress
            # bot can resolve it by path on the site itself.
            return
        parent_id = int(found["id"])

    if parent_id is None:
        return
    if page_id is not None and int(parent_id) == int(page_id):
        raise ValueError("A page cannot be its own parent")

    parent = (
        await connection.execute(
            text(
                """
                SELECT id, campaign_id, slug, wp_page_id
                FROM campaign_pages
                WHERE id = :parent_id
                """
            ),
            {"parent_id": parent_id},
        )
    ).mappings().one_or_none()
    if parent is None:
        raise ValueError(f"parent_campaign_page_id {parent_id} does not exist")
    if campaign_id is not None and int(parent["campaign_id"]) != int(campaign_id):
        raise ValueError("The parent page belongs to a different campaign")

    params["parent_campaign_page_id"] = int(parent["id"])
    params["parent_wp_page_id"] = parent["wp_page_id"]
    params["parent_slug"] = parent["slug"] or parent_slug or None


def _admin_config(resource: str) -> dict[str, Any]:
    config = _ADMIN_TABLES.get(resource)
    if config is None:
        raise ValueError(f"Unsupported admin resource: {resource}")
    return config


def _admin_payload(
    config: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    allowed = set(config["columns"])
    fields = [field for field in config["columns"] if field in payload]
    unknown = sorted(set(payload).difference(allowed))
    if unknown:
        raise ValueError(f"Unsupported fields: {', '.join(unknown)}")

    params: dict[str, Any] = {}
    json_columns = set(config["json_columns"])
    for field in fields:
        value = payload[field]
        params[field] = (
            json.dumps(value, ensure_ascii=False)
            if field in json_columns
            else value
        )
    return fields, params


def _admin_value_sql(config: dict[str, Any], field: str) -> str:
    if field in set(config["json_columns"]):
        return f"CAST(:{field} AS jsonb)"
    return f":{field}"


def _table_columns(config: dict[str, Any]) -> tuple[str, ...]:
    return ("id", *config["columns"], "created_at", "updated_at")

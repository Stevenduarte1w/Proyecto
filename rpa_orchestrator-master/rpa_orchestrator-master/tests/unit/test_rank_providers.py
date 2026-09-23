from __future__ import annotations

import json

import httpx
import pytest

from orchestrator.infrastructure.seo_agent.rankings import (
    BrightLocalRankClient,
    SerperRankClient,
)


async def test_brightlocal_client_returns_exact_page_position() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(201, json={"request_id": "request-123"})
        return httpx.Response(
            200,
            json={
                "ready": True,
                "success": True,
                "rankings": {
                    "organic": [
                        {
                            "rank": 7,
                            "serp": {
                                "website_url": "https://www.example.com/local-page/",
                                "position": 7,
                            },
                        }
                    ]
                },
                "results": {},
            },
        )

    client = BrightLocalRankClient(
        api_key="secret-key",
        num_results=100,
        poll_interval_seconds=0.01,
        transport=httpx.MockTransport(handler),
    )

    result = await client.check_position(
        url="https://example.com/local-page",
        keyword="local service",
        location="Bogotá, Colombia",
        country="CO",
        language="es-CO",
    )

    assert result["position"] == 7
    assert result["matched_url"] == "https://www.example.com/local-page/"
    assert [request.url.path for request in requests] == [
        "/data/v1/rankings/search",
        "/data/v1/rankings/results/request-123",
    ]
    request_payload = json.loads(requests[0].content)
    assert request_payload == {
        "search_engine": "google",
        "search_term": "local service",
        "country": "COL",
        "geo_location": {"name": "Bogotá, Colombia"},
        "lang": "es",
        "num_results": 100,
        "match_criteria": {"website_urls": ["https://example.com/local-page"]},
    }
    assert requests[0].headers["x-api-key"] == "secret-key"


async def test_brightlocal_client_reports_page_outside_top_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"request_id": "request-456"})
        return httpx.Response(
            200,
            json={
                "ready": True,
                "success": True,
                "rankings": {"organic": []},
                "results": {
                    "organic": [
                        {
                            "website_url": "https://competitor.example/",
                            "position": 1,
                        }
                    ]
                },
            },
        )

    client = BrightLocalRankClient(
        api_key="secret-key",
        transport=httpx.MockTransport(handler),
    )

    result = await client.check_position(
        url="https://example.com/local-page",
        keyword="local service",
        location="Chicago, Illinois",
        country="USA",
        language="en",
    )

    assert result["position"] is None
    assert result["matched_url"] is None


async def test_brightlocal_client_requires_api_key() -> None:
    client = BrightLocalRankClient(api_key="")

    with pytest.raises(RuntimeError, match="BRIGHTLOCAL_API_KEY"):
        await client.check_position(
            url="https://example.com/",
            keyword="local service",
            location="Chicago, Illinois",
            country="USA",
            language="en",
        )


async def test_serper_client_returns_exact_page_position() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "title": "Local page",
                        "link": "https://www.example.com/local-page/",
                        "position": 7,
                    },
                    {
                        "title": "Competitor",
                        "link": "https://competitor.example/",
                        "position": 8,
                    },
                ]
            },
        )

    client = SerperRankClient(
        api_key="serper-secret",
        num_results=100,
        transport=httpx.MockTransport(handler),
    )

    result = await client.check_position(
        url="https://example.com/local-page",
        keyword="local service",
        location="Bogotá, Colombia",
        country="COL",
        language="es-CO",
    )

    assert result["position"] == 7
    assert result["matched_url"] == "https://www.example.com/local-page/"
    assert len(requests) == 1
    assert requests[0].url.path == "/search"
    assert requests[0].headers["x-api-key"] == "serper-secret"
    assert json.loads(requests[0].content) == {
        "q": "local service",
        "location": "Bogotá, Colombia",
        "gl": "co",
        "hl": "es",
        "num": 100,
    }


async def test_serper_client_reports_page_outside_top_results() -> None:
    client = SerperRankClient(
        api_key="serper-secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "organic": [
                        {
                            "link": "https://competitor.example/",
                            "position": 1,
                        }
                    ]
                },
            )
        ),
    )

    result = await client.check_position(
        url="https://example.com/local-page",
        keyword="local service",
        location="Chicago, Illinois",
        country="US",
        language="en",
    )

    assert result["position"] is None
    assert result["matched_url"] is None


async def test_serper_client_requires_api_key() -> None:
    client = SerperRankClient(api_key="")

    with pytest.raises(RuntimeError, match="SERPER_API_KEY"):
        await client.check_position(
            url="https://example.com/",
            keyword="local service",
            location="Chicago, Illinois",
            country="US",
            language="en",
        )

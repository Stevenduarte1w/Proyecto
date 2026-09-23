from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

import httpx

_ALPHA2_TO_ALPHA3 = {
    "AR": "ARG",
    "AU": "AUS",
    "BR": "BRA",
    "CA": "CAN",
    "CL": "CHL",
    "CO": "COL",
    "DE": "DEU",
    "DO": "DOM",
    "EC": "ECU",
    "ES": "ESP",
    "FR": "FRA",
    "GB": "GBR",
    "IE": "IRL",
    "IT": "ITA",
    "MX": "MEX",
    "NL": "NLD",
    "NZ": "NZL",
    "PE": "PER",
    "PR": "PRI",
    "SG": "SGP",
    "US": "USA",
    "ZA": "ZAF",
}
_ALPHA3_TO_ALPHA2 = {alpha3: alpha2 for alpha2, alpha3 in _ALPHA2_TO_ALPHA3.items()}


class BrightLocalRankClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.brightlocal.com",
        num_results: int = 100,
        timeout_seconds: float = 45.0,
        poll_interval_seconds: float = 1.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._num_results = min(max(num_results, 1), 100)
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._transport = transport

    async def check_position(
        self,
        *,
        url: str,
        keyword: str,
        location: str,
        country: str,
        language: str,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise RuntimeError("BRIGHTLOCAL_API_KEY is not configured")

        payload = {
            "search_engine": "google",
            "search_term": keyword,
            "country": _alpha3_country(country),
            "geo_location": {"name": location},
            "lang": (language or "en").split("-", 1)[0].lower(),
            "num_results": self._num_results,
            "match_criteria": {"website_urls": [url]},
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
        }
        timeout = httpx.Timeout(self._timeout_seconds)
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=timeout,
                transport=self._transport,
            ) as client:
                response = await client.post("/data/v1/rankings/search", json=payload)
                _raise_for_status(response)
                request_id = str(_json_object(response).get("request_id") or "").strip()
                if not request_id:
                    raise RuntimeError("BrightLocal did not return a request_id")

                result = await self._wait_for_result(client, request_id)
        except httpx.RequestError as exc:
            raise RuntimeError("Could not connect to BrightLocal") from exc

        match = _find_exact_organic_match(result, url)
        return {
            "request_id": request_id,
            "position": match["position"] if match else None,
            "matched_url": match["url"] if match else None,
            "max_results": self._num_results,
        }

    async def _wait_for_result(
        self,
        client: httpx.AsyncClient,
        request_id: str,
    ) -> dict[str, Any]:
        deadline = monotonic() + self._timeout_seconds
        while True:
            response = await client.get(f"/data/v1/rankings/results/{request_id}")
            _raise_for_status(response)
            result = _json_object(response)
            if result.get("ready") is True:
                if result.get("success") is not True:
                    raise RuntimeError("BrightLocal could not complete the ranking request")
                return result
            if monotonic() >= deadline:
                raise RuntimeError("BrightLocal ranking request timed out")
            await asyncio.sleep(self._poll_interval_seconds)


class SerperRankClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://google.serper.dev",
        num_results: int = 100,
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._num_results = min(max(num_results, 1), 100)
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def check_position(
        self,
        *,
        url: str,
        keyword: str,
        location: str,
        country: str,
        language: str,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise RuntimeError("SERPER_API_KEY is not configured")

        payload = {
            "q": keyword,
            "location": location,
            "gl": _alpha2_country(country).lower(),
            "hl": (language or "en").split("-", 1)[0].lower(),
            "num": self._num_results,
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-KEY": self._api_key,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=httpx.Timeout(self._timeout_seconds),
                transport=self._transport,
            ) as client:
                response = await client.post("/search", json=payload)
                _raise_provider_status(response, "Serper")
                result = _provider_json_object(response, "Serper")
        except httpx.RequestError as exc:
            raise RuntimeError("Could not connect to Serper") from exc

        match = _find_serper_organic_match(result, url)
        return {
            "request_id": None,
            "position": match["position"] if match else None,
            "matched_url": match["url"] if match else None,
            "max_results": self._num_results,
        }


def _alpha3_country(country: str) -> str:
    code = country.strip().upper()
    if len(code) == 3:
        return code
    if code in _ALPHA2_TO_ALPHA3:
        return _ALPHA2_TO_ALPHA3[code]
    raise ValueError(
        f"Country '{country}' must use an ISO alpha-3 code supported by BrightLocal"
    )


def _alpha2_country(country: str) -> str:
    code = country.strip().upper()
    if len(code) == 2:
        return code
    if code in _ALPHA3_TO_ALPHA2:
        return _ALPHA3_TO_ALPHA2[code]
    raise ValueError(f"Country '{country}' must use an ISO alpha-2 code supported by Serper")


def _find_exact_organic_match(
    payload: dict[str, Any],
    expected_url: str,
) -> dict[str, Any] | None:
    expected = _normalized_url(expected_url)
    matches: list[dict[str, Any]] = []
    rankings = payload.get("rankings")
    results = payload.get("results")
    groups = []
    if isinstance(rankings, dict):
        groups.append(rankings.get("organic"))
    if isinstance(results, dict):
        groups.append(results.get("organic"))

    for group in groups:
        if not isinstance(group, list):
            continue
        for entry in group:
            if not isinstance(entry, dict):
                continue
            serp = entry.get("serp")
            result = serp if isinstance(serp, dict) else entry
            result_url = str(
                result.get("website_url") or result.get("serp_result_url") or ""
            )
            if not result_url or _normalized_url(result_url) != expected:
                continue
            position = _positive_int(entry.get("rank")) or _positive_int(
                result.get("position")
            )
            if position is not None:
                matches.append({"position": position, "url": result_url})

    return min(matches, key=lambda item: int(item["position"])) if matches else None


def _find_serper_organic_match(
    payload: dict[str, Any],
    expected_url: str,
) -> dict[str, Any] | None:
    expected = _normalized_url(expected_url)
    organic = payload.get("organic")
    if not isinstance(organic, list):
        return None

    matches: list[dict[str, Any]] = []
    for result in organic:
        if not isinstance(result, dict):
            continue
        result_url = str(result.get("link") or "")
        if not result_url or _normalized_url(result_url) != expected:
            continue
        position = _positive_int(result.get("position"))
        if position is not None:
            matches.append({"position": position, "url": result_url})
    return min(matches, key=lambda item: int(item["position"])) if matches else None


def _normalized_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value if "://" in value else f"https://{value}")
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/") or "/"
    return host, path


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _json_object(response: httpx.Response) -> dict[str, Any]:
    return _provider_json_object(response, "BrightLocal")


def _provider_json_object(response: httpx.Response, provider: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{provider} returned an invalid JSON response") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{provider} returned an unexpected response")
    return payload


def _raise_for_status(response: httpx.Response) -> None:
    _raise_provider_status(response, "BrightLocal")


def _raise_provider_status(response: httpx.Response, provider: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = f"HTTP {response.status_code}"
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message = payload.get("message") or payload.get("error")
                if message:
                    detail = f"{detail}: {message}"
        except ValueError:
            pass
        raise RuntimeError(f"{provider} request failed ({detail})") from exc

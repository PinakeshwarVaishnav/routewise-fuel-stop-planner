"""A very small, cache-aware client for openrouteservice.

An uncached trip uses at most three provider requests:
  1. geocode the start,
  2. geocode the finish,
  3. request the driving route once (including its GeoJSON geometry).

Geocoding and route responses are cached independently, so repeat requests
usually need fewer calls.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache


class ORSError(Exception):
    """Base exception for routing-provider failures."""


class LocationNotFound(ORSError):
    """Raised when a location cannot be resolved to a point in the U.S."""


class ProviderUnavailable(ORSError):
    """Raised when the external service is unavailable or returns bad data."""


class OpenRouteServiceClient:
    """Small wrapper around the ORS geocoding and driving-directions APIs."""

    def __init__(self) -> None:
        self.api_key = settings.ORS_API_KEY
        self.base_url = settings.ORS_BASE_URL.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": self.api_key,
                "Accept": "application/json",
                "User-Agent": "RouteWiseFuelPlanner/1.0 (+assessment-demo)",
            }
        )

    def _require_api_key(self) -> None:
        if not self.api_key:
            raise ProviderUnavailable(
                "ORS_API_KEY is not configured. Add your OpenRouteService key to .env."
            )

    @staticmethod
    def _cache_key(prefix: str, value: str) -> str:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return f"routewise:{prefix}:{digest}"

    def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        self._require_api_key()
        try:
            response = self.session.request(method, url, timeout=(3.05, 15), **kwargs)
        except requests.RequestException as exc:
            raise ProviderUnavailable(
                "The routing provider could not be reached."
            ) from exc

        if response.status_code == 404:
            raise LocationNotFound("The requested location or route was not found.")

        if not response.ok:
            # Do not expose request headers or the API key in client-facing errors.
            detail = "The routing provider rejected the request."
            try:
                provider_error = response.json().get("error", {}).get("message")
                if provider_error:
                    detail = str(provider_error)[:250]
            except (ValueError, AttributeError):
                pass
            raise ProviderUnavailable(detail)

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderUnavailable(
                "The routing provider returned invalid JSON."
            ) from exc

        if not isinstance(payload, dict):
            raise ProviderUnavailable(
                "The routing provider returned an unexpected response."
            )
        return payload

    def geocode_us(self, query: str) -> dict[str, Any]:
        """Resolve a place/address, explicitly constraining results to the U.S."""
        cache_key = self._cache_key("geocode", query.casefold().strip())
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        payload = self._request_json(
            "GET",
            f"{self.base_url}/geocode/search",
            params={
                "text": query,
                "boundary.country": "US",
                "size": 1,
            },
        )
        features = payload.get("features") or []
        if not features:
            raise LocationNotFound(f"No U.S. match was found for '{query}'.")

        feature = features[0]
        properties = feature.get("properties") or {}
        country_code = str(
            properties.get("country_a")
            or properties.get("country_code")
            or properties.get("country")
            or ""
        ).upper()
        # The query is already country-bounded. This second check protects us
        # from a provider response that does not honour the requested boundary.
        if country_code not in {
            "USA",
            "US",
            "UNITED STATES",
            "UNITED STATES OF AMERICA",
        }:
            raise LocationNotFound(
                f"'{query}' did not resolve to a location in the United States."
            )

        coordinates = (feature.get("geometry") or {}).get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise ProviderUnavailable(
                "The geocoder returned a location without coordinates."
            )

        longitude, latitude = float(coordinates[0]), float(coordinates[1])
        result = {
            "label": properties.get("label") or query,
            "latitude": latitude,
            "longitude": longitude,
        }
        cache.set(cache_key, result, settings.ORS_GEOCODE_CACHE_SECONDS)
        return result

    def driving_route(
        self,
        start: dict[str, Any],
        finish: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch one GeoJSON driving route (distance, duration, and geometry)."""
        coordinates = [
            [float(start["longitude"]), float(start["latitude"])],
            [float(finish["longitude"]), float(finish["latitude"])],
        ]
        cache_material = json.dumps(coordinates, separators=(",", ":"))
        cache_key = self._cache_key("route", cache_material)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        payload = self._request_json(
            "POST",
            f"{self.base_url}/v2/directions/driving-car/geojson",
            json={"coordinates": coordinates},
            headers={
                "Accept": "application/geo+json",
            },
        )
        features = payload.get("features") or []
        if not features:
            raise ProviderUnavailable("The routing provider returned no driving route.")

        feature = features[0]
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        summary = properties.get("summary") or {}
        route_coordinates = geometry.get("coordinates")
        distance_meters = summary.get("distance")
        duration_seconds = summary.get("duration")

        if (
            geometry.get("type") != "LineString"
            or not isinstance(route_coordinates, list)
            or len(route_coordinates) < 2
            or distance_meters is None
            or duration_seconds is None
        ):
            raise ProviderUnavailable(
                "The routing provider returned incomplete route data."
            )

        result = {
            "type": "LineString",
            "coordinates": route_coordinates,
            "distance_meters": float(distance_meters),
            "duration_seconds": float(duration_seconds),
        }
        cache.set(cache_key, result, settings.ORS_ROUTE_CACHE_SECONDS)
        return result

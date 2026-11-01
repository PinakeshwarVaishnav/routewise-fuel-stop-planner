from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from fuel_planner.services.ors_client import (
    LocationNotFound,
    OpenRouteServiceClient,
    ProviderUnavailable,
)


@override_settings(
    ORS_API_KEY="test-key",
    ORS_BASE_URL="https://api.openrouteservice.org",
    ORS_GEOCODE_CACHE_SECONDS=1800,
    ORS_ROUTE_CACHE_SECONDS=1800,
)
class OpenRouteServiceClientTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @staticmethod
    def response(payload, status_code=200):
        response = Mock()
        response.status_code = status_code
        response.ok = 200 <= status_code < 300
        response.json.return_value = payload
        return response

    @patch("fuel_planner.services.ors_client.requests.Session.request")
    def test_geocoder_is_constrained_to_the_united_states(self, request_mock):
        request_mock.return_value = self.response(
            {
                "features": [
                    {
                        "geometry": {"coordinates": [-118.24, 34.05]},
                        "properties": {
                            "country_a": "USA",
                            "label": "Los Angeles, California, United States",
                        },
                    }
                ]
            }
        )

        result = OpenRouteServiceClient().geocode_us("Los Angeles, CA")

        self.assertEqual(result["latitude"], 34.05)
        self.assertEqual(result["longitude"], -118.24)
        self.assertEqual(request_mock.call_count, 1)
        self.assertEqual(
            request_mock.call_args.kwargs["params"]["boundary.country"], "US"
        )

    @patch("fuel_planner.services.ors_client.requests.Session.request")
    def test_geocoder_rejects_a_non_us_result(self, request_mock):
        request_mock.return_value = self.response(
            {
                "features": [
                    {
                        "geometry": {"coordinates": [-123.12, 49.28]},
                        "properties": {"country_a": "CAN", "label": "Vancouver"},
                    }
                ]
            }
        )

        with self.assertRaises(LocationNotFound):
            OpenRouteServiceClient().geocode_us("Vancouver")

    @patch("fuel_planner.services.ors_client.requests.Session.request")
    def test_route_geometry_is_fetched_once_and_cached(self, request_mock):
        request_mock.return_value = self.response(
            {
                "features": [
                    {
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-118.24, 34.05], [-117.16, 32.72]],
                        },
                        "properties": {
                            "summary": {"distance": 200000, "duration": 7200}
                        },
                    }
                ]
            }
        )
        client = OpenRouteServiceClient()
        start = {"latitude": 34.05, "longitude": -118.24}
        finish = {"latitude": 32.72, "longitude": -117.16}

        first = client.driving_route(start, finish)
        second = client.driving_route(start, finish)

        self.assertEqual(first, second)
        self.assertEqual(first["distance_meters"], 200000.0)
        self.assertEqual(request_mock.call_count, 1)
        self.assertIn(
            "/v2/directions/driving-car/geojson", request_mock.call_args.args[1]
        )

    @override_settings(ORS_API_KEY="")
    def test_missing_api_key_fails_with_a_safe_configuration_error(self):
        with self.assertRaises(ProviderUnavailable):
            OpenRouteServiceClient().geocode_us("Austin, TX")

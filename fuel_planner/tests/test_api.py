from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient


@override_settings(ORS_API_KEY="test-key")
class PlanApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("fuel_planner.views.OpenRouteServiceClient.driving_route")
    @patch("fuel_planner.views.OpenRouteServiceClient.geocode_us")
    def test_api_returns_route_summary_and_fuel_plan(self, geocode_mock, route_mock):
        geocode_mock.side_effect = [
            {"label": "Austin, Texas", "latitude": 30.2672, "longitude": -97.7431},
            {"label": "Houston, Texas", "latitude": 29.7604, "longitude": -95.3698},
        ]
        # About 600 miles: this is a deliberately synthetic route so the test
        # verifies response assembly without using the live mapping provider.
        route_mock.return_value = {
            "type": "LineString",
            "coordinates": [[-97.7431, 30.2672], [-96.0, 30.0], [-95.3698, 29.7604]],
            "distance_meters": 965606.0,
            "duration_seconds": 30000.0,
        }

        response = self.client.post(
            "/api/v1/plan/",
            {"start": "Austin, TX", "finish": "Houston, TX"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("route", response.data)
        self.assertIn("fuel_plan", response.data)
        self.assertIn("is_feasible", response.data["fuel_plan"])
        self.assertIn("stops", response.data["fuel_plan"])
        self.assertEqual(route_mock.call_count, 1)
        self.assertEqual(geocode_mock.call_count, 2)

    def test_invalid_request_is_rejected_before_provider_calls(self):
        with patch(
            "fuel_planner.views.OpenRouteServiceClient.geocode_us"
        ) as geocode_mock:
            response = self.client.post(
                "/api/v1/plan/",
                {"start": "", "finish": "New York, NY"},
                format="json",
            )

        self.assertEqual(response.status_code, 400)
        geocode_mock.assert_not_called()

    def test_health_endpoint(self):
        response = self.client.get("/api/v1/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "ok")

from django.test import SimpleTestCase

from fuel_planner.services.optimizer import minimum_cost_fuel_plan, with_total_trip_cost


def station(station_id, position, price, city):
    return {
        "station_id": station_id,
        "name": f"{city} Travel Center",
        "address": f"I-{station_id} exit",
        "city": city,
        "state": "TX",
        "price_per_gallon": price,
        "latitude": 30.0,
        "longitude": -97.0,
        "location_precision": "exact",
        "route_position_miles": position,
        "distance_from_route_miles": 0.2,
    }


class FuelOptimizerTests(SimpleTestCase):
    def test_full_starting_tank_covers_short_route(self):
        result = minimum_cost_fuel_plan(
            420,
            [station(1, 100, 3.10, "Austin")],
        )

        self.assertTrue(result["is_feasible"])
        self.assertEqual(result["stops"], [])
        self.assertEqual(result["fuel_purchased_gallons"], 0.0)
        self.assertEqual(str(result["fuel_cost_usd"]), "0.00")

    def test_optimizer_can_skip_a_cheaper_but_unnecessary_intermediate_stop(self):
        result = minimum_cost_fuel_plan(
            650,
            [
                station(1, 100, 4.00, "Expensive One Hundred"),
                station(2, 450, 2.00, "Cheap Four Fifty"),
                station(3, 600, 4.00, "Expensive Six Hundred"),
            ],
        )

        self.assertTrue(result["is_feasible"])
        self.assertEqual([stop["station_id"] for stop in result["stops"]], [2])
        self.assertEqual(result["fuel_purchased_gallons"], 15.0)
        self.assertEqual(str(result["fuel_cost_usd"]), "30.00")
        self.assertEqual(result["stops"][0]["gallons_to_purchase"], 15.0)

    def test_global_plan_uses_two_stops_when_that_is_cheaper(self):
        result = minimum_cost_fuel_plan(
            900,
            [
                station(1, 100, 4.00, "Expensive One Hundred"),
                station(2, 400, 2.00, "Cheap Four Hundred"),
                station(3, 600, 3.00, "Middle Six Hundred"),
                station(4, 800, 1.00, "Cheapest Eight Hundred"),
            ],
        )

        self.assertTrue(result["is_feasible"])
        self.assertEqual([stop["station_id"] for stop in result["stops"]], [2, 4])
        self.assertEqual(result["fuel_purchased_gallons"], 40.0)
        self.assertEqual(str(result["fuel_cost_usd"]), "70.00")
        self.assertTrue(
            all(stop["gallons_to_purchase"] > 0 for stop in result["stops"])
        )

    def test_carries_remaining_fuel_forward_before_buying_at_a_higher_price(self):
        result = minimum_cost_fuel_plan(
            900,
            [
                station(1, 100, 2.00, "Low Price One Hundred"),
                station(2, 400, 2.10, "Slightly Higher Four Hundred"),
                station(3, 600, 3.00, "Expensive Six Hundred"),
                station(4, 850, 1.00, "Cheapest Eight Fifty"),
            ],
        )

        self.assertTrue(result["is_feasible"])
        self.assertEqual([stop["station_id"] for stop in result["stops"]], [1, 2, 4])
        self.assertEqual(result["fuel_purchased_gallons"], 40.0)
        self.assertEqual(str(result["fuel_cost_usd"]), "77.50")

    def test_reports_unreachable_route_when_station_gaps_exceed_tank_range(self):
        result = minimum_cost_fuel_plan(
            1100,
            [
                station(1, 100, 3.00, "First Town"),
                station(2, 700, 3.00, "Second Town"),
            ],
        )

        self.assertFalse(result["is_feasible"])
        self.assertEqual(result["stops"], [])
        self.assertIsNone(result["fuel_cost_usd"])

    def test_same_city_marker_uses_only_the_cheapest_candidate(self):
        result = minimum_cost_fuel_plan(
            700,
            [
                station(1, 250.01, 4.20, "Same City"),
                station(2, 250.05, 2.20, "Same City"),
            ],
        )

        self.assertTrue(result["is_feasible"])
        self.assertEqual(result["stops"][0]["station_id"], 2)

    def test_rejects_invalid_vehicle_parameters(self):
        with self.assertRaises(ValueError):
            minimum_cost_fuel_plan(100, [], tank_range_miles=0)

    def test_small_purchases_are_rounded_up_to_the_minimum(self):
        stations = [
            station(1, 495, 3.00, "Almost Empty"),
            station(2, 505, 2.00, "Cheaper Ahead"),
        ]
        old = minimum_cost_fuel_plan(900, stations)
        new = minimum_cost_fuel_plan(900, stations, min_purchase_gallons=5)
        self.assertAlmostEqual(old["stops"][0]["gallons_to_purchase"], 0.5, places=3)
        self.assertGreaterEqual(new["stops"][0]["gallons_to_purchase"], 5.0)
        self.assertTrue(new["is_feasible"])
        self.assertAlmostEqual(new["fuel_purchased_gallons"], 40.0, places=2)

    def test_tiny_price_difference_is_ignored_with_min_saving(self):
        stations = [
            station(1, 300, 3.20, "Start Town"),
            station(2, 320, 3.19, "Penny Cheaper"),
        ]
        plan = minimum_cost_fuel_plan(900, stations, min_saving_per_gallon=0.05)
        self.assertNotIn(2, [s["station_id"] for s in plan["stops"][:1]])

    def test_total_trip_cost_includes_starting_tank_for_short_trip(self):
        plan = minimum_cost_fuel_plan(300, [])
        total = with_total_trip_cost(plan, 3.00, "test price")
        self.assertEqual(str(total["fuel_cost_usd"]), "0.00")
        self.assertEqual(str(total["total_trip_cost_usd"]), "90.00")  # 30 gal x $3

    def test_total_trip_cost_covers_every_gallon_burned(self):
        plan = minimum_cost_fuel_plan(
            900, [station(1, 400, 2.00, "Cheap"), station(2, 800, 1.00, "Cheapest")]
        )
        total = with_total_trip_cost(plan, 2.00, "test price")
        # 90 gal burned = 50 starting (at $2) + 40 bought en route.
        self.assertEqual(plan["total_fuel_used_gallons"], 90.0)
        self.assertEqual(
            str(total["total_trip_cost_usd"]),
            str(total["fuel_cost_usd"] + total["starting_tank_cost_usd"]),
        )

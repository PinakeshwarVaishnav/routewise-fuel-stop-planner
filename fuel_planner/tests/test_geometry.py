from django.test import SimpleTestCase

from fuel_planner.services.geometry import haversine_miles, project_point_onto_route


class GeometryTests(SimpleTestCase):
    def test_haversine_distance_for_one_degree_of_latitude(self):
        self.assertAlmostEqual(haversine_miles(0, 0, 1, 0), 69.09, delta=0.2)

    def test_projects_a_point_onto_a_straight_east_west_route(self):
        # ORS coordinates are [longitude, latitude]. The point is north of
        # the middle of the route, so its route mileage should be about half.
        route = [[-100.0, 35.0], [-99.0, 35.0]]
        route_position, distance_from_route = project_point_onto_route(
            35.1, -99.5, route
        )

        self.assertAlmostEqual(route_position, 28.2, delta=0.5)
        self.assertAlmostEqual(distance_from_route, 6.9, delta=0.2)


class SimplifyRouteTests(SimpleTestCase):
    def test_straight_line_collapses_and_endpoints_are_kept(self):
        from fuel_planner.services.geometry import simplify_route
        line = [[-100 + i * 0.01, 35.0] for i in range(1000)]
        out = simplify_route(line, 0.25)
        self.assertEqual(out[0], [-100.0, 35.0])
        self.assertEqual(out[-1], [round(line[-1][0], 5), 35.0])
        self.assertLess(len(out), 5)


class StationsNearRouteTests(SimpleTestCase):
    def test_keeps_nearby_stations_and_drops_far_ones_with_accurate_mileage(self):
        from types import SimpleNamespace
        from fuel_planner.services.geometry import stations_near_route

        route = [[-100 + i * 0.01, 35.0] for i in range(2001)]  # ~1,130 miles east
        def st(i, lat, lon):
            return SimpleNamespace(
                station_id=i, name="s", address="a", city="c", state="TX",
                price_per_gallon=3.0, latitude=lat, longitude=lon,
                location_precision="place_point",
            )
        stations = [st(1, 35.02, -90.0), st(2, 36.5, -90.0), st(3, 35.0, -101.0)]
        found = stations_near_route(stations, route, max_deviation_miles=5)
        self.assertEqual([c["station_id"] for c in found], [1])
        self.assertAlmostEqual(found[0]["route_position_miles"], 566, delta=5)
        self.assertLess(found[0]["distance_from_route_miles"], 3)

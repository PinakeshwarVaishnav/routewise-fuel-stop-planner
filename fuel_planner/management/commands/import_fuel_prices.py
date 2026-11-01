"""Import the assessment CSV and enrich station rows with U.S. place points.

Usage:
    python manage.py import_fuel_prices --csv data/fuel_prices.csv

The Census Gazetteer is downloaded once and reused. Its internal place points
are approximate stand-ins for station coordinates because the assessment CSV
contains no latitude/longitude. Supply --coordinates with exact station
coordinates to replace those approximate locations where available.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import urllib.request
import zipfile
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from fuel_planner.models import FuelStation


CENSUS_GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2025_Gazetteer/2025_Gaz_place_national.zip"
)
US_STATES_AND_DC = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN "
    "MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT "
    "VA WA WV WI WY DC".split()
)


def normalize_place_name(value: str) -> str:
    """Normalize a place name for a conservative state+name lookup."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = value.casefold().strip()
    value = re.sub(
        r"\b(city|town|village|borough|cdp|municipality|plantation|balance)\b$",
        "",
        value,
    )
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def load_place_points(
    gazetteer_zip: Path,
) -> dict[tuple[str, str], tuple[float, float]]:
    """Read the national Census Places Gazetteer into (state, name) -> lat/lon."""
    if not gazetteer_zip.exists():
        gazetteer_zip.parent.mkdir(parents=True, exist_ok=True)
        try:
            urllib.request.urlretrieve(CENSUS_GAZETTEER_URL, gazetteer_zip)
        except Exception as exc:  # noqa: BLE001 - include network errors as command errors
            raise CommandError(
                "Could not download the Census Gazetteer. Download the national "
                "Places Gazetteer ZIP from the Census Bureau and pass it with "
                "--gazetteer /path/to/2025_Gaz_place_national.zip."
            ) from exc

    try:
        archive = zipfile.ZipFile(gazetteer_zip)
    except (OSError, zipfile.BadZipFile) as exc:
        raise CommandError(
            f"The Gazetteer file is not a readable ZIP: {gazetteer_zip}"
        ) from exc

    text_files = [name for name in archive.namelist() if name.lower().endswith(".txt")]
    if not text_files:
        raise CommandError(
            "No pipe-delimited TXT file was found inside the Gazetteer ZIP."
        )

    points: dict[tuple[str, str], tuple[float, float]] = {}
    areas: dict[tuple[str, str], int] = {}

    with archive.open(text_files[0]) as raw_file:
        text_file = io.TextIOWrapper(raw_file, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text_file, delimiter="|")
        required = {"USPS", "NAME", "INTPTLAT", "INTPTLONG"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise CommandError(
                "The Census Gazetteer does not have the expected columns."
            )

        for row in reader:
            state = (row.get("USPS") or "").strip().upper()
            if state not in US_STATES_AND_DC:
                continue

            city_key = (state, normalize_place_name(row.get("NAME") or ""))
            if not city_key[1]:
                continue

            try:
                latitude = float(row["INTPTLAT"])
                longitude = float(row["INTPTLONG"])
                land_area = int(float(row.get("ALAND") or 0))
            except (TypeError, ValueError):
                continue

            # Some cities and census-designated places can share a normalized
            # name. Retain the larger place as the least-surprising fallback.
            if land_area >= areas.get(city_key, -1):
                areas[city_key] = land_area
                points[city_key] = (latitude, longitude)

    return points


def read_exact_coordinates(path: Path | None) -> dict[int, tuple[float, float]]:
    """Read optional exact station coordinates from a small user-maintained CSV."""
    if path is None:
        return {}
    if not path.exists():
        raise CommandError(f"Coordinate override file does not exist: {path}")

    result: dict[int, tuple[float, float]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            raise CommandError("The coordinate override file needs a header row.")
        columns = {name.casefold(): name for name in reader.fieldnames}

        id_column = columns.get("opis truckstop id") or columns.get("station_id")
        latitude_column = columns.get("latitude") or columns.get("lat")
        longitude_column = (
            columns.get("longitude") or columns.get("lon") or columns.get("lng")
        )
        if not all((id_column, latitude_column, longitude_column)):
            raise CommandError(
                "Coordinate CSV headers must include OPIS Truckstop ID (or station_id), "
                "latitude, and longitude."
            )

        for row in reader:
            try:
                station_id = int(row[id_column])
                latitude = float(row[latitude_column])
                longitude = float(row[longitude_column])
            except (TypeError, ValueError):
                continue
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                continue
            result[station_id] = (latitude, longitude)
    return result


class Command(BaseCommand):
    help = (
        "Import the provided fuel prices and attach approximate U.S. place coordinates."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            default=str(settings.BASE_DIR / "data" / "fuel_prices.csv"),
            help="Path to the assessment fuel-price CSV.",
        )
        parser.add_argument(
            "--gazetteer",
            default=str(settings.BASE_DIR / "data" / "2025_Gaz_place_national.zip"),
            help="Path to a downloaded Census national places Gazetteer ZIP.",
        )
        parser.add_argument(
            "--coordinates",
            default=None,
            help="Optional CSV of exact station coordinates to override place points.",
        )

    def handle(self, *args, **options):
        source_path = Path(options["csv"])
        gazetteer_path = Path(options["gazetteer"])
        coordinates_path = (
            Path(options["coordinates"]) if options["coordinates"] else None
        )

        if not source_path.exists():
            raise CommandError(f"Fuel-price CSV was not found: {source_path}")

        place_points = load_place_points(gazetteer_path)
        exact_points = read_exact_coordinates(coordinates_path)

        # First consolidate repeated station IDs. The file has no date column,
        # so we deliberately retain the lowest observed value and disclose it.
        grouped: dict[int, dict[str, object]] = {}
        rejected_state_rows = 0
        rejected_price_rows = 0

        with source_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            required_columns = {
                "OPIS Truckstop ID",
                "Truckstop Name",
                "Address",
                "City",
                "State",
                "Rack ID",
                "Retail Price",
            }
            if not reader.fieldnames or not required_columns.issubset(
                set(reader.fieldnames)
            ):
                raise CommandError(
                    "The CSV headers do not match the supplied assessment file."
                )

            for row in reader:
                state = (row.get("State") or "").strip().upper()
                if state not in US_STATES_AND_DC:
                    rejected_state_rows += 1
                    continue

                try:
                    station_id = int(row["OPIS Truckstop ID"])
                    price = Decimal(row["Retail Price"].strip())
                except (TypeError, ValueError, InvalidOperation):
                    rejected_price_rows += 1
                    continue
                if price <= 0:
                    rejected_price_rows += 1
                    continue

                station = grouped.get(station_id)
                if station is None:
                    grouped[station_id] = {
                        "name": row["Truckstop Name"].strip(),
                        "address": row["Address"].strip(),
                        "city": row["City"].strip(),
                        "state": state,
                        "rack_id": int(row["Rack ID"])
                        if row["Rack ID"].strip()
                        else None,
                        "price": price,
                        "count": 1,
                    }
                else:
                    station["price"] = min(station["price"], price)
                    station["count"] = int(station["count"]) + 1

        duplicate_observations_merged = sum(
            int(station["count"]) - 1 for station in grouped.values()
        )
        repeated_station_ids = sum(
            1 for station in grouped.values() if int(station["count"]) > 1
        )

        imported = 0
        place_point_matches = 0
        exact_matches = 0
        unmatched = 0

        for station_id, source in grouped.items():
            # Exact coordinates always win. This includes coordinates imported
            # manually on an earlier run, so a later price refresh cannot
            # silently downgrade a precise station to a city-centre point.
            existing = FuelStation.objects.filter(station_id=station_id).first()
            if station_id in exact_points:
                latitude, longitude = exact_points[station_id]
                precision = FuelStation.LocationPrecision.EXACT
                exact_matches += 1
            elif (
                existing
                and existing.location_precision == FuelStation.LocationPrecision.EXACT
                and existing.latitude is not None
                and existing.longitude is not None
            ):
                latitude = float(existing.latitude)
                longitude = float(existing.longitude)
                precision = FuelStation.LocationPrecision.EXACT
                exact_matches += 1
            else:
                city_key = (
                    str(source["state"]),
                    normalize_place_name(str(source["city"])),
                )
                point = place_points.get(city_key)
                if point is None:
                    latitude = longitude = None
                    precision = FuelStation.LocationPrecision.PLACE_POINT
                    unmatched += 1
                else:
                    latitude, longitude = point
                    precision = FuelStation.LocationPrecision.PLACE_POINT
                    place_point_matches += 1

            defaults = {
                "name": source["name"],
                "address": source["address"],
                "city": source["city"],
                "state": source["state"],
                "rack_id": source["rack_id"],
                "price_per_gallon": source["price"],
                "latitude": latitude,
                "longitude": longitude,
                "location_precision": precision,
                "source_observations": source["count"],
            }
            FuelStation.objects.update_or_create(
                station_id=station_id, defaults=defaults
            )
            imported += 1

        self.stdout.write(
            self.style.SUCCESS(f"Imported/updated {imported:,} U.S. stations.")
        )
        self.stdout.write(f"Place-point matches: {place_point_matches:,}")
        self.stdout.write(f"Exact coordinate overrides: {exact_matches:,}")
        self.stdout.write(
            self.style.WARNING(f"Stations without coordinates: {unmatched:,}")
        )
        self.stdout.write(f"Non-U.S. source rows ignored: {rejected_state_rows:,}")
        self.stdout.write(f"Rows with invalid prices ignored: {rejected_price_rows:,}")
        self.stdout.write(
            f"Repeated station IDs: {repeated_station_ids:,}; "
            f"duplicate observations merged: {duplicate_observations_merged:,}"
        )
        self.stdout.write(
            "Duplicate policy: one row per station ID; keep the lowest observed price "
            "because the CSV contains no observation timestamp."
        )

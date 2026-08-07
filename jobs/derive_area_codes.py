"""The recorded area-code derivation (partner-lead-assignment.md §6, Phase 0).

Produces THE subscription list — the DNC registry area codes to subscribe for a
partner — from where the partner calls: a base point and a radius. The design's
original Chatsworth table was never reproducible (method unrecorded) and two
independent re-measurements dispute its fifth code (661 vs 747); this script IS
the recorded method, and its output supersedes every earlier table.

The method, pinned (every input named so a re-run is a re-derivation):
  - Geocode source: US Census 2023 ZCTA National Gazetteer (INTPTLAT/INTPTLONG),
    trimmed verbatim into `config/zcta-centroids-2023.csv` (33,791 rows) from
    https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_zcta_national.zip
  - Base point: the ZCTA centroid of the base ZIP — the SAME centroid method as
    every contact, so no separate geocoder enters the chain. Default base:
    91311 (the Chatsworth seed address's ZIP, config/seeds.json).
  - Distance: haversine, statute miles, earth radius 3958.8 mi.
  - Contact universe: phone-bearing, non-seed contacts (READONLY_DATABASE_URL);
    ZIP = first 5 digits of addr_zip. Contacts whose ZIP is absent from the
    gazetteer are COUNTED AND REPORTED, never silently dropped (the known
    ~5,400-statewide caveat).
  - Area code: digits 2-4 of the E.164 phone (the national prefix).
"""

import argparse
import csv
import math
import os
import sys
from collections import Counter
from pathlib import Path

EARTH_RADIUS_MILES = 3958.8
CENTROIDS = Path(__file__).resolve().parent.parent / "config" / "zcta-centroids-2023.csv"


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def area_code(phone_e164: str) -> str:
    return phone_e164.removeprefix("+1")[:3]


def load_centroids() -> dict[str, tuple[float, float]]:
    with open(CENTROIDS) as handle:
        return {
            row["zcta"]: (float(row["lat"]), float(row["lon"]))
            for row in csv.DictReader(handle)
        }


def derive(base_zip: str, radius_miles: float, centroids, contacts):
    """contacts: iterable of (phone_e164, addr_zip). Returns the analysis dict."""
    if base_zip not in centroids:
        raise SystemExit(f"base ZIP {base_zip} is not in the gazetteer")
    base = centroids[base_zip]

    in_radius: Counter = Counter()
    total = unmapped = 0
    for phone, addr_zip in contacts:
        total += 1
        zip5 = (addr_zip or "").strip()[:5]
        point = centroids.get(zip5)
        if point is None:
            unmapped += 1
            continue
        if haversine_miles(base[0], base[1], point[0], point[1]) <= radius_miles:
            in_radius[area_code(phone)] += 1

    covered = sum(in_radius.values())
    ranked = in_radius.most_common()
    return {
        "base_zip": base_zip,
        "radius_miles": radius_miles,
        "callable_total": total,
        "zip_unmapped": unmapped,
        "in_radius": covered,
        "distinct_codes": len(ranked),
        "ranked": ranked,
    }


def _print_report(result: dict, top: int) -> list[str]:
    ranked = result["ranked"]
    head = ranked[:top]
    head_total = sum(n for _, n in head)
    print(
        f"base {result['base_zip']}  radius {result['radius_miles']:g} mi  "
        f"(gazetteer: {CENTROIDS.name})"
    )
    print(
        f"  callable contacts statewide: {result['callable_total']}  "
        f"(ZIP unmapped, excluded from radius math: {result['zip_unmapped']})"
    )
    print(
        f"  in radius: {result['in_radius']}  across {result['distinct_codes']} area codes"
    )
    if result["in_radius"]:
        pct = 100.0 * head_total / result["in_radius"]
        print(f"  top {top} covers {head_total} ({pct:.1f}%):")
    for code, n in head:
        print(f"    {code}  {n}")
    tail = result["in_radius"] - head_total
    print(f"  long tail (unassignable without paid codes): {tail}")
    return [code for code, _ in head]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="derive_area_codes",
        description="Derive the DNC-subscription area codes from a partner's base "
        "ZIP and calling radius (partner-lead-assignment.md §6 — the recorded, "
        "re-runnable method; its output IS the subscription list).",
        epilog=(
            "Examples:\n"
            "  uv run python -m jobs.derive_area_codes                    # Chatsworth, 20 mi\n"
            "  uv run python -m jobs.derive_area_codes --radius 15\n"
            "  uv run python -m jobs.derive_area_codes --base-zip 90210 --top 5\n"
            "  uv run python -m jobs.derive_area_codes --radii 10 15 20 25  # the dispute table\n\n"
            "Then record the answer:\n"
            "  uv run python -m jobs.subscribe_area_codes add <the codes it prints>\n\n"
            "Requires READONLY_DATABASE_URL — make targets source .env; this module "
            "does not."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base-zip", default="91311",
        help="base ZCTA (default 91311 — the Chatsworth seed's ZIP)",
    )
    parser.add_argument(
        "--radius", type=float, default=20.0,
        help="calling radius in statute miles (default 20)",
    )
    parser.add_argument(
        "--top", type=int, default=5,
        help="how many codes to recommend (default 5 — the registry's free tier)",
    )
    parser.add_argument(
        "--radii", type=float, nargs="+", default=None,
        help="ALSO print the ranking at each of these radii (the 661-vs-747 "
        "dispute check)",
    )
    args = parser.parse_args(argv)

    import psycopg

    url = os.environ.get("READONLY_DATABASE_URL")
    if not url:
        print("READONLY_DATABASE_URL is not set", file=sys.stderr)
        return 2
    centroids = load_centroids()
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select phone_e164, addr_zip from contacts "
                "where phone_e164 is not null and is_seed = false"
            )
            contacts = cur.fetchall()

    picks = _print_report(derive(args.base_zip, args.radius, centroids, contacts), args.top)
    for radius in args.radii or []:
        print()
        _print_report(derive(args.base_zip, radius, centroids, contacts), args.top)

    print(
        f"\nderived ranking: {' '.join(picks)}  "
        "(policy 2026-08-01: start with ONE code — the densest; "
        "more on request when performing)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""FBN-CA intake adapter — LA County Fictitious Business Name export → canonical
intake CSV (the shape service.contacts.load_list ingests).

One adapter per purchased-list format; the spine never learns a vendor's columns.
This one:
  * keeps `FBN Statement` rows only — amendments/renewals re-describe the same
    business, abandonments/withdrawals are closures (mailing them is waste);
  * optionally filters to one filing year (--year);
  * dedupes on FilingNumber, then keeps the newest filing per (business name, zip)
    so refiled businesses appear once;
  * prefixes the list key (`fbn-ca-<FilingNumber>`) so keys never collide across lists;
  * leaves trade empty (an FBN filer's trade is unknown) and sets a segment, which is
    what makes the row targetable.

Stdlib only; no service imports — adapters run upstream of the spine.
"""

import argparse
import csv
import sys

CANONICAL_FIELDS = [
    "list_key",
    "business_name",
    "contact_name",
    "trade",
    "license_class",
    "phone",
    "email",
    "addr_line1",
    "addr_line2",
    "addr_city",
    "addr_state",
    "addr_zip",
    "segment",
    "do_not_mail",
]


def convert(rows, year: int | None = None) -> list[dict[str, str]]:
    """Filter + dedupe + map raw FBN rows to canonical intake rows."""
    seen_filings: set[str] = set()
    by_business: dict[tuple[str, str], dict[str, str]] = {}

    for row in rows:
        if (row.get("FilingType") or "").strip() != "FBN Statement":
            continue
        filed = (row.get("FiledTS") or "").strip()
        if year is not None and not filed.startswith(str(year)):
            continue
        filing = (row.get("FilingNumber") or "").strip()
        if not filing or filing in seen_filings:
            continue
        seen_filings.add(filing)

        name = (row.get("BusinessName") or "").strip()
        zip5 = (row.get("BusinessZipCode") or "").strip()[:5]
        business = (name.upper(), zip5)
        prev = by_business.get(business)
        if prev is not None and prev["_filed"] >= filed:
            continue

        by_business[business] = {
            "_filed": filed,
            "list_key": f"fbn-ca-{filing}",
            "business_name": name,
            "contact_name": (row.get("RegisteredOwnerName") or "").strip(),
            "trade": "",
            "license_class": "",
            "phone": "",
            "email": "",
            "addr_line1": (row.get("BusinessAddress") or "").strip(),
            "addr_line2": (row.get("BusinessAddressAdditional") or "").strip(),
            "addr_city": (row.get("BusinessCity") or "").strip(),
            "addr_state": (row.get("BusinessState") or "").strip().upper(),
            "addr_zip": zip5,
            "segment": f"fbn-ca-{year}" if year is not None else "fbn-ca",
            "do_not_mail": "",
        }

    return [
        {k: v for k, v in r.items() if k != "_filed"} for r in by_business.values()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="LA County FBN export -> canonical intake CSV for load_list.",
        epilog=(
            "examples:\n"
            "  python -m intake.fbn_ca Fictitious_Business_Name.csv --year 2026 -o fbn-2026.csv\n"
            "  python -m intake.fbn_ca raw.csv            # all years, to stdout\n"
            "then load via the web UI (/intake, source e.g. 'fbn-ca-2026') or load_list()."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="raw FBN CSV (LA County Registrar-Recorder export)")
    parser.add_argument("--year", type=int, help="keep only filings from this year")
    parser.add_argument(
        "-o", "--output", help="canonical CSV path (default: stdout)", default=None
    )
    args = parser.parse_args(argv)

    with open(args.input, newline="", encoding="utf-8-sig") as handle:
        converted = convert(csv.DictReader(handle), year=args.year)

    out = open(args.output, "w", newline="") if args.output else sys.stdout
    try:
        writer = csv.DictWriter(out, fieldnames=CANONICAL_FIELDS)
        writer.writeheader()
        writer.writerows(converted)
    finally:
        if args.output:
            out.close()
    print(f"{len(converted)} canonical rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

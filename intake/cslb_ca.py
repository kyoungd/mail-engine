"""CSLB-CA intake adapter — CSLB Master License export → canonical intake CSV (the
shape service.contacts.load_list ingests).

The primary list: statewide CA licensed contractors, 100% phone coverage, authoritative
trade via license classifications. Defaults: CLEAR licenses only, NMC trades only.
Data-shape facts and filter traps (notably the WC-Exempt trap) live in
docs/list-shapes.md — read it before adding filters.

Stdlib only; no service imports — adapters run upstream of the spine.
"""

import argparse
import csv
import re
import sys

from intake.fbn_ca import CANONICAL_FIELDS

# License classification -> NMC trade, in priority order: a multi-class license gets
# the FIRST matching trade below (specific trades outrank B general building).
TRADE_BY_CLASS = {
    "C36": "plumber",
    "C20": "hvac",
    "C10": "electrician",
    "C39": "roofer",
    "C27": "landscaper",
    "C33": "painter",
}

# Classes where WC-Exempt is legally impossible regardless of employees, so the
# --wc-exempt solo filter would silently drop the whole trade (docs/list-shapes.md):
# C-39 roofing (pre-SB-216 law) + SB 216 Phase 1 (C-8, C-20, C-22, D-49, since 2023).
# SB 216 Phase 2 (delayed by SB 1455 to 2028-01-01) will void the flag for ALL classes.
WC_EXEMPT_INVALID_CLASSES = {"C39", "C8", "C20", "C22", "D49"}


def _classes(raw: str) -> list[str]:
    return [
        c.strip().upper().replace("-", "")
        for c in re.split(r"[|;,]", raw or "")
        if c.strip()
    ]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def convert(
    rows,
    counties: set[str] | None = None,
    classes: set[str] | None = None,
    wc_exempt_only: bool = False,
    include_suspended: bool = False,
) -> list[dict[str, str]]:
    """Filter + dedupe + map raw CSLB rows to canonical intake rows."""
    wanted = {c.upper().replace("-", "") for c in classes} if classes else None
    county_set = {c.strip().lower() for c in counties} if counties else None
    seen: set[str] = set()
    out: list[dict[str, str]] = []

    for row in rows:
        license_no = (row.get("LicenseNo") or "").strip()
        if not license_no or license_no in seen:
            continue

        if not include_suspended and (row.get("PrimaryStatus") or "").strip() != "CLEAR":
            continue

        held = _classes(row.get("Classifications(s)") or "")
        trade = next(
            (t for c, t in TRADE_BY_CLASS.items() if c in held), None
        )
        if trade is None:
            continue
        if wanted is not None and not (set(held) & wanted):
            continue

        county = (row.get("County") or "").strip()
        if county_set is not None and county.lower() not in county_set:
            continue

        if wc_exempt_only and (row.get("WorkersCompCoverageType") or "").strip() != "Exempt":
            continue

        seen.add(license_no)
        geo = _slug(county) or (row.get("State") or "").strip().lower() or "ca"
        out.append(
            {
                "list_key": f"cslb-{license_no}",
                "business_name": (row.get("BusinessName") or "").strip(),
                "contact_name": (row.get("FullBusinessName") or "").strip(),
                "trade": trade,
                "license_class": "|".join(held),
                "phone": (row.get("BusinessPhone") or "").strip(),
                "email": "",
                "addr_line1": (row.get("MailingAddress") or "").strip(),
                "addr_line2": "",
                "addr_city": (row.get("City") or "").strip(),
                "addr_state": (row.get("State") or "").strip().upper(),
                "addr_zip": (row.get("ZIPCode") or "").strip()[:5],
                "segment": f"{trade}-{geo}",
                "do_not_mail": "",
            }
        )

    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CSLB Master License export -> canonical intake CSV for load_list.",
        epilog=(
            "examples:\n"
            "  python -m intake.cslb_ca MasterLicenseData.csv --county 'Los Angeles' "
            "--classes C36 -o la-plumbers.csv\n"
            "  python -m intake.cslb_ca MasterLicenseData.csv --wc-exempt   # solo operators\n"
            "then load via the web UI (/intake, source e.g. 'cslb-ca') or load_list().\n\n"
            "TRAP: --wc-exempt is void for C-39/C-8/C-20/C-22/D-49 (WC mandatory for those\n"
            "classes regardless of employees) and decays for everyone by 2028 (SB 216 / SB\n"
            "1455). See docs/list-shapes.md."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="raw CSLB CSV (MasterLicenseData.csv)")
    parser.add_argument(
        "--county", action="append", help="keep only this county (repeatable)"
    )
    parser.add_argument(
        "--classes",
        help="comma-separated license classes to keep (e.g. C36,C20); default: any NMC trade",
    )
    parser.add_argument(
        "--wc-exempt",
        action="store_true",
        help="keep only WC-Exempt licensees (solo operators — see trap in epilog)",
    )
    parser.add_argument(
        "--include-suspended",
        action="store_true",
        help="keep non-CLEAR licenses too (default: CLEAR only)",
    )
    parser.add_argument(
        "-o", "--output", help="canonical CSV path (default: stdout)", default=None
    )
    args = parser.parse_args(argv)

    if args.wc_exempt and args.classes:
        voided = {
            c.strip().upper().replace("-", "") for c in args.classes.split(",")
        } & WC_EXEMPT_INVALID_CLASSES
        if voided:
            print(
                f"warning: --wc-exempt is void for {sorted(voided)} — WC is mandatory "
                "for those classes regardless of employees (docs/list-shapes.md)",
                file=sys.stderr,
            )

    with open(args.input, newline="", encoding="utf-8-sig", errors="replace") as handle:
        converted = convert(
            csv.DictReader(handle),
            counties=set(args.county) if args.county else None,
            classes=set(args.classes.split(",")) if args.classes else None,
            wc_exempt_only=args.wc_exempt,
            include_suspended=args.include_suspended,
        )

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

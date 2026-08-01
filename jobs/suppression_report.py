"""The Phase 2 before/after stage-migration report — a phase DELIVERABLE, reviewed
by the operator before the first post-migration nightly (partner-lead-assignment
implementation plan, Phase 2 "Consequence to surface, not hide").

Contacts currently SUPPRESSED via do-not-mail-on-load or returned mail move stage
on the first v3 recompute and become visible to the judgment rules again — their
phones were never the problem. This report quantifies the move BEFORE it happens:
the opt_out payload-reason breakdown (the historical-event trap), who stays
suppressed, who moves, and how many land in the stages the judgment rules read
(`responded` / `in_conversation` — hot_response, quiet_reengage, lost_aging).

Read-only: it simulates v3 derivation in memory and writes nothing.
"""

import argparse
import json
from collections import Counter

from psycopg import sql

from db.readonly import readonly_connection
from derivation.rules import derive_stage, is_address_undeliverable
from domain.types import ContactFlags
from service.ingestion import EVENT_COLS, event_from_row


def build_report() -> dict:
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select payload->>'reason', count(*) from events "
                "where type = 'contact.opt_out' group by 1"
            )
            opt_out_reasons = {(r or "<none>"): n for r, n in cur.fetchall()}

            cur.execute(
                "select id, stage_snapshot, do_not_mail, do_not_text from contacts "
                "where stage_snapshot = 'suppressed' and is_seed = false"
            )
            suppressed = cur.fetchall()

            by_contact: dict = {}
            if suppressed:
                cur.execute(
                    sql.SQL(
                        "select {cols} from events where contact_id = any(%s) "
                        "and type <> 'contact.dnc_checked' "
                        "order by contact_id, occurred_at"
                    ).format(cols=EVENT_COLS),
                    ([c[0] for c in suppressed],),
                )
                for row in cur.fetchall():
                    by_contact.setdefault(row[1], []).append(event_from_row(row))

    stays = moves = 0
    predicted_stages: Counter = Counter()
    newly_undeliverable = 0
    for cid, _stage, do_not_mail, do_not_text in suppressed:
        events = by_contact.get(cid, [])
        new_stage = derive_stage(
            events, ContactFlags(do_not_mail=do_not_mail, do_not_text=do_not_text)
        )
        if new_stage.value == "suppressed":
            stays += 1
        else:
            moves += 1
            predicted_stages[new_stage.value] += 1
            if is_address_undeliverable(events):
                newly_undeliverable += 1

    judgment_visible = (
        predicted_stages["responded"] + predicted_stages["in_conversation"]
    )
    return {
        "currently_suppressed": len(suppressed),
        "opt_out_reasons": opt_out_reasons,
        "predicted": {
            "stays_suppressed": stays,
            "moves_stage": moves,
            "stage_distribution": dict(predicted_stages),
            "gains_address_undeliverable": newly_undeliverable,
            "newly_visible_to_judgment_rules": judgment_visible,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="suppression_report",
        description="Before/after report for the v3 suppression split: who moves "
        "stage on the first recompute, and why (Phase 2 deliverable — review "
        "BEFORE the first post-migration nightly).",
        epilog=(
            "Examples:\n"
            "  uv run python -m jobs.suppression_report        # human-readable\n"
            "  uv run python -m jobs.suppression_report --json # machine-readable\n\n"
            "Read-only (READONLY_DATABASE_URL); simulates v3 in memory, writes nothing."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)

    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    predicted = report["predicted"]
    print("Suppression split — before/after (v3 simulated, nothing written)")
    print(f"  currently SUPPRESSED:            {report['currently_suppressed']}")
    print(f"  historical opt_out reasons:      {report['opt_out_reasons']}")
    print(f"  stays suppressed under v3:       {predicted['stays_suppressed']}")
    print(f"  moves stage on first recompute:  {predicted['moves_stage']}")
    print(f"    landing stages:                {predicted['stage_distribution']}")
    print(f"    gains address_undeliverable:   {predicted['gains_address_undeliverable']}")
    print(
        f"    newly visible to judgment:     "
        f"{predicted['newly_visible_to_judgment_rules']}  "
        "(hot_response / quiet_reengage / lost_aging read these stages)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

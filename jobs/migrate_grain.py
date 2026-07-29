"""The one-time contact-grain migration (design `ingest-contact-migration.md` §7).

Migration `0008` carries the *additive* DDL and runs first. This script owns everything
order-dependent — the data steps AND the constraint swap — inside one transaction
(Postgres DDL is transactional). The swap is split around the data steps because its
halves point in opposite directions: the `pieces` unique-constraint drop **must precede**
the repoint (two wave-1 pieces landing on one `(contact, wave)` would violate the live
constraint and roll back every `--execute`), while the phone-unique index **cannot exist
before** the merge (1,785 duplicated phones) and `list_key` cannot be dropped before the
backfill reads it.

**Dry run is the default, and it is not a simulation.** It runs steps 1–6 in the
transaction, computes the full report, then rolls back — the identical code path
`--execute` commits. A report produced by a parallel "what would happen" implementation
would be a different program, and the thing being gated is this one.

Steps 1–6 are one transaction; 7–9 follow it:

  1. preflight (fail loud)      5. survivor field updates + delete losers
  2. backfill intake tables     6. post-merge DDL (phone-unique index, drop columns)
  3. compute merge groups       7. recompute_state()  — after commit, owns its own txn
  4. drop constraint + repoint  8. before/after report   9. verify_addresses (ordinary job)

Cutover is stop-the-world: pull the release → apply `0008` → `migrate_grain --execute` →
only then use any verb. Old code must never run after (it inserts `contacts.list_key`,
which step 6 drops); new code must never run before (a phone-attach against the pre-merge
table would attach to an arbitrary one of 1,785 duplicated-phone contacts).
"""

import argparse
import sys
from collections import defaultdict
from typing import Any

import psycopg

from db.session import _owner_url
from intake.cslb_ca import TRADE_BY_CLASS
from resolution.pick import coalesce_email, pick_winner

__all__ = ["coalesce_email", "pick_winner"]  # re-exported: §3's rule lives in resolution

# Which intake table each contact source belongs to, and the `list_key` prefix that must
# agree with it. The intake UI defaults `source='cslb'`, so a mis-sourced FBN upload is a
# real class of error rather than a hypothetical — hence the cross-check in step 1.
SOURCE_TABLE = (("cslb", "intake_cslb_ca", "cslb-"), ("fbn", "intake_fbn_ca", "fbn-ca-"))

INTAKE_TABLES = ("intake_cslb_ca", "intake_fbn_ca")


class PreflightHalt(Exception):
    """A preflight condition failed. Never caught inside this module — the whole point
    is that the operator reads it and decides, rather than the script routing around it."""


# --------------------------------------------------------------------------------------
# The re-run guard (implementation plan, ground rule 4)
# --------------------------------------------------------------------------------------


def swap_applied(conn) -> bool:
    """Post-swap is detected by the absence of `contacts.list_key` — step 6 drops it."""
    with conn.cursor() as cur:
        cur.execute(
            "select 1 from information_schema.columns "
            "where table_schema = 'public' and table_name = 'contacts' "
            "and column_name = 'list_key'"
        )
        return cur.fetchone() is None


def ensure_swapped(url: str | None = None) -> str:
    """Idempotent entry point for `make migrate` and test-DB setup.

    Pinned contract (ground rule 4), because this runs unattended:

      post-swap                -> clean no-op ("already migrated")
      pre-swap, WITH data      -> loud halt; the full dry-run ceremony is required.
                                  Never auto-merge someone's populated database.
      pre-swap, EMPTY (fresh)  -> apply the swap automatically; merging over zero rows
                                  is trivially the ceremony.

    The guard must never mask a prod preflight halt — prod is never empty, so it takes
    the middle branch and stops.
    """
    with psycopg.connect(url or _owner_url()) as conn:
        if swap_applied(conn):
            return "already migrated"
        with conn.cursor() as cur:
            cur.execute("select count(*) from contacts")
            row = cur.fetchone()
            populated = bool(row and row[0])
        if populated:
            raise PreflightHalt(
                "contacts is populated and the grain swap has not run. This is not a "
                "step to automate: run `uv run python -m jobs.migrate_grain` (dry run), "
                "read the report, then re-run with --execute. For a dev database the "
                "remedy is drop/recreate -> make migrate -> re-ingest."
            )
        _apply_swap_ddl(conn)
        conn.commit()
        return "swap applied to empty database"


def _apply_swap_ddl(conn) -> None:
    """Step 6's DDL, factored out so the empty-database path and the migration proper
    produce byte-identical schemas rather than two definitions that can drift."""
    with conn.cursor() as cur:
        cur.execute("alter table pieces drop constraint if exists pieces_contact_id_wave_id_key")
        # Possible only after the merge: 1,785 phones span 3,772 rows before it. Seeds are
        # exempt (founder samples are not businesses) and null phones never collide.
        cur.execute(
            "create unique index if not exists contacts_phone_unique on contacts (phone_e164) "
            "where phone_e164 is not null and is_seed = false"
        )
        for column in ("list_key", "trade", "license_class"):
            cur.execute(f"alter table contacts drop column if exists {column}")


# --------------------------------------------------------------------------------------
# §3's pick rule
# --------------------------------------------------------------------------------------


def derive_trades(license_class: str | None) -> list[str]:
    """Every NMC trade the stored classes map to, sorted distinct union — the same shape
    the adapter now emits into the canonical CSV, derived here for rows that predate it."""
    if not license_class:
        return []
    held = {c.strip().upper().replace("-", "") for c in license_class.replace(",", "|").split("|")}
    return sorted({t for c, t in TRADE_BY_CLASS.items() if c in held})


# --------------------------------------------------------------------------------------
# Step 1 — preflight
# --------------------------------------------------------------------------------------


def source_distribution(cur) -> list[tuple[str, str, int]]:
    """The report's opening section: the real `(source, list_key-prefix)` distribution.
    The preflight's outcome hinges on this fact and no document records it — loads
    *should* have used `cslb` and `fbn-ca-2026`, but should is not a measurement."""
    cur.execute(
        "select coalesce(source, '<null>'), "
        "coalesce(substring(list_key from '^[a-z-]+'), '<null>'), count(*) "
        "from contacts where is_seed = false group by 1, 2 order by 3 desc"
    )
    return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def preflight(cur) -> None:
    """Fail loud. Every halt here is a condition the operator must resolve deliberately —
    there is no --force, and the named remedy for a genuine mis-source is --fix-source."""
    cur.execute(
        "select id from waves where status::text in ('approved', 'executing') limit 5"
    )
    active = [r[0] for r in cur.fetchall()]
    if active:
        raise PreflightHalt(
            f"{len(active)} wave(s) in approved/executing: {active}. A drop resumed across "
            "the merge would mint new mailer codes for survivor contacts (codes hash "
            "contact ids) and double-mail merged businesses with the constraint gone. "
            "Finish or cancel the wave first."
        )

    cur.execute(
        "select coalesce(source, '<null>'), coalesce(list_key, '<null>'), count(*) "
        "from contacts where is_seed = false group by 1, 2"
    )
    bad: list[str] = []
    for source, list_key, _ in cur.fetchall():
        table = table_for_source(source)
        if table is None:
            bad.append(f"source={source!r} maps to no intake table")
            continue
        prefix = next(p for _, t, p in SOURCE_TABLE if t == table)
        if not str(list_key).startswith(prefix):
            bad.append(f"source={source!r} but list_key={list_key!r} (expected {prefix}*)")
    if bad:
        sample = "; ".join(sorted(set(bad))[:5])
        raise PreflightHalt(
            f"{len(set(bad))} source/list_key-prefix disagreement(s): {sample}. "
            "Read the distribution report, then use "
            "--fix-source <list_key-prefix>=<correct-source>. Never raw SQL, and never "
            "silent routing on the prefix."
        )

    cur.execute(
        "select count(*) from activation a where a.contact_id in ("
        "  select c.id from contacts c"
        "  where c.phone_e164 is not null and c.is_seed = false"
        "    and c.phone_e164 in ("
        "      select phone_e164 from contacts"
        "      where phone_e164 is not null and is_seed = false"
        "      group by phone_e164 having count(*) > 1))"
    )
    row = cur.fetchone()
    if row and row[0]:
        raise PreflightHalt(
            f"{row[0]} activation row(s) belong to contacts that would merge. Expected "
            "zero (TD-2: nothing writes the activation table). Resolve before merging."
        )

    cur.execute("select count(distinct owner) from contacts")
    row = cur.fetchone()
    if row and row[0] and row[0] > 1:
        raise PreflightHalt(
            "contacts.owner is not uniform. The merge defines reconciliation for "
            "suppression and next-action but deliberately NOT for owner, because owner "
            "had no writer when this was designed. If partner assignment has shipped, "
            "the merge needs an owner rule before it can run — that is a design change, "
            "not a script change."
        )


def table_for_source(source: str | None) -> str | None:
    for prefix, table, _ in SOURCE_TABLE:
        if source and source.startswith(prefix):
            return table
    return None


def fix_source(cur, mapping: str) -> int:
    """`--fix-source cslb-=cslb` — scripted, logged, operator-invoked after reading the
    distribution report. Exists so the remedy for a mis-source is never raw SQL."""
    prefix, _, correct = mapping.partition("=")
    if not prefix or not correct:
        raise PreflightHalt(f"--fix-source expects <list_key-prefix>=<source>, got {mapping!r}")
    cur.execute(
        "update contacts set source = %s where is_seed = false and list_key like %s",
        (correct, f"{prefix}%"),
    )
    return cur.rowcount


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="migrate_grain",
        description="One-time contact-grain migration: license-record rows become "
        "business-grain contacts (design ingest-contact-migration.md §7).",
        epilog=(
            "Dry run is the DEFAULT and is not a simulation: it runs steps 1-6 in the "
            "transaction, prints the report, then rolls back — the same code path "
            "--execute commits.\n\n"
            "Examples:\n"
            "  uv run python -m jobs.migrate_grain                    # dry run + report\n"
            "  uv run python -m jobs.migrate_grain --execute          # commit it\n"
            "  uv run python -m jobs.migrate_grain --fix-source fbn-ca-=fbn-ca-2026\n"
            "  uv run python -m jobs.migrate_grain --check            # report the guard's view\n"
            "  uv run python -m jobs.migrate_grain --ensure-swapped   # unattended guard (make migrate)\n\n"
            "Requires OWNER_DATABASE_URL (make targets source .env; this module does not).\n"
            "Apply migration 0008 BEFORE running this."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--execute", action="store_true", help="commit the migration (default: dry run + rollback)"
    )
    parser.add_argument(
        "--fix-source",
        metavar="PREFIX=SOURCE",
        help="repair a mis-sourced load before preflight, e.g. fbn-ca-=fbn-ca-2026",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the swap has run and stop (no transaction opened)",
    )
    parser.add_argument(
        "--ensure-swapped",
        action="store_true",
        help="ground rule 4's unattended guard: no-op post-swap, halt on a populated "
        "pre-swap DB, apply the swap on an empty one (used by make migrate + test setup)",
    )
    args = parser.parse_args(argv)

    url = _owner_url()
    if args.ensure_swapped:
        print(ensure_swapped(url))
        return 0
    with psycopg.connect(url) as conn:
        if args.check:
            print("post-swap (already migrated)" if swap_applied(conn) else "pre-swap")
            return 0
        if swap_applied(conn):
            print("already migrated — contacts.list_key is gone; nothing to do.")
            return 0
        print(f"{'EXECUTING' if args.execute else 'DRY RUN (will roll back)'} — {url.split('@')[-1]}")
        return 1 if _run(conn, args) else 0


CONTACT_FIELDS = (
    "id, list_key, business_name, contact_name, trade, license_class, phone_e164, "
    "email, addr_line1, addr_line2, addr_city, addr_state, addr_zip, segment, "
    "do_not_mail, do_not_text, next_action_at, next_action_note, source, is_seed"
)


def _fetch_contacts(cur) -> list[dict[str, Any]]:
    cur.execute(f"select {CONTACT_FIELDS} from contacts")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def backfill_intake(cur, rows: list[dict[str, Any]]) -> dict[str, int]:
    """Step 2 — every current contact row IS an intake row. Source columns copy verbatim
    (including `do_not_mail`); `trades` is derived from the stored `license_class` via the
    adapter's map, since these rows predate the canonical column. `contact_id` is the row's
    own contact for now; step 4 repoints losers. Seeds get `seed_key` and no intake row —
    a founder sample is not a business."""
    counts = {"intake_cslb_ca": 0, "intake_fbn_ca": 0, "seeds": 0}
    for row in rows:
        if row["is_seed"]:
            cur.execute(
                "update contacts set seed_key = %s where id = %s", (row["list_key"], row["id"])
            )
            counts["seeds"] += 1
            continue
        table = table_for_source(row["source"])
        assert table, "preflight guarantees a table for every non-seed row"
        cur.execute(
            f"insert into {table} (list_key, contact_id, business_name, contact_name, "
            "trade, trades, license_class, phone_e164, email, addr_line1, addr_line2, "
            "addr_city, addr_state, addr_zip, segment, do_not_mail) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (list_key) do nothing",
            (
                row["list_key"],
                row["id"],
                row["business_name"],
                row["contact_name"],
                row["trade"],
                derive_trades(row["license_class"]),
                row["license_class"],
                row["phone_e164"],
                row["email"],
                row["addr_line1"],
                row["addr_line2"],
                row["addr_city"],
                row["addr_state"],
                row["addr_zip"],
                row["segment"],
                row["do_not_mail"],
            ),
        )
        counts[table] += 1
    return counts


def merge_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Step 3 — group by `phone_e164` over CSLB-sourced rows ONLY. Identity is per-source
    (§3): FBN never phone-groups, even if a phone-bearing filing ever appears, so a phone
    on an FBN row can never merge two filings."""
    by_phone: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["is_seed"] or not row["phone_e164"]:
            continue
        if table_for_source(row["source"]) != "intake_cslb_ca":
            continue
        by_phone[row["phone_e164"]].append(row)

    groups = []
    for phone, members in by_phone.items():
        if len(members) < 2:
            continue
        winner = pick_winner(members)
        groups.append(
            {
                "phone": phone,
                "winner": winner,
                "losers": [m for m in members if m["id"] != winner["id"]],
                "email": coalesce_email(members, winner),
                "members": members,
            }
        )
    return groups


def apply_merge(cur, groups: list[dict[str, Any]]) -> dict[str, int]:
    """Steps 4-5. The constraint drop MUST precede the repoint: §2.3's own premise — two
    wave-1 pieces landing on one (contact, wave) — would violate the live constraint and
    roll back the whole run."""
    cur.execute("alter table pieces drop constraint if exists pieces_contact_id_wave_id_key")

    merged_next_actions = 0
    for group in groups:
        survivor = group["winner"]["id"]
        loser_ids = [loser["id"] for loser in group["losers"]]

        for table in (*INTAKE_TABLES, "pieces", "events"):
            cur.execute(
                f"update {table} set contact_id = %s where contact_id = any(%s)",
                (survivor, loser_ids),
            )
        cur.executemany(
            "insert into contact_merge_map (old_contact_id, new_contact_id) values (%s, %s) "
            "on conflict (old_contact_id) do nothing",
            [(loser, survivor) for loser in loser_ids],
        )

        # Suppression is absorbing: a suppressed loser suppresses the merged business.
        if any(m["do_not_mail"] for m in group["members"]):
            cur.execute("update contacts set do_not_mail = true where id = %s", (survivor,))
        if any(m["do_not_text"] for m in group["members"]):
            cur.execute("update contacts set do_not_text = true where id = %s", (survivor,))

        # Founder-authored state must survive — the same contract
        # test_human_set_next_action_survives_recompute pins for recompute.
        dated = sorted(
            (m for m in group["members"] if m["next_action_at"]),
            key=lambda m: m["next_action_at"],
        )
        if dated:
            note = dated[0]["next_action_note"] or ""
            others = [m["next_action_note"] for m in dated[1:] if m["next_action_note"]]
            if others:
                note = f"{note} | merged: {' | '.join(others)}"
                merged_next_actions += 1
            cur.execute(
                "update contacts set next_action_at = %s, next_action_note = %s where id = %s",
                (dated[0]["next_action_at"], note, survivor),
            )

        cur.execute(
            "update contacts set email = %s, business_name = %s, contact_name = %s, "
            "segment = %s, source = %s, addr_line1 = %s, addr_line2 = %s, addr_city = %s, "
            "addr_state = %s, addr_zip = %s where id = %s",
            (
                group["email"],
                group["winner"]["business_name"],
                group["winner"]["contact_name"],
                group["winner"]["segment"],
                group["winner"]["source"],
                group["winner"]["addr_line1"],
                group["winner"]["addr_line2"],
                group["winner"]["addr_city"],
                group["winner"]["addr_state"],
                group["winner"]["addr_zip"],
                survivor,
            ),
        )
        cur.execute("delete from contacts where id = any(%s)", (loser_ids,))

    return {"merged_next_actions": merged_next_actions}


def mark_primaries(cur, rows: list[dict[str, Any]], groups: list[dict[str, Any]]) -> int:
    """Exactly one primary per contact — DB-enforced by 0008's partial unique index, so a
    miscount here fails loudly rather than misrouting mail. Grouped contacts: the winner
    row. Ungrouped: their own single row."""
    winners = {group["winner"]["list_key"] for group in groups}
    grouped = {m["id"] for group in groups for m in group["members"]}
    keys = [r["list_key"] for r in rows if not r["is_seed"] and r["id"] not in grouped]
    keys.extend(winners)
    marked = 0
    for table in INTAKE_TABLES:
        cur.execute(
            f"update {table} set is_primary = true where list_key = any(%s)", (keys,)
        )
        marked += cur.rowcount
    return marked


def _run(conn, args) -> bool:
    """Steps 1-6 in one transaction. Returns True on halt.

    Dry run reaches the identical end state and rolls back, so the report below is
    measured from the real thing rather than predicted by a second implementation.
    """
    try:
        with conn.cursor() as cur:
            if args.fix_source:
                print(f"--fix-source: {fix_source(cur, args.fix_source)} row(s) re-sourced")

            print("\n== source / list_key-prefix distribution ==")
            for source, prefix, count in source_distribution(cur):
                print(f"  {source:<16} {prefix:<12} {count:>8}")

            preflight(cur)
            print("preflight: OK")

            rows = _fetch_contacts(cur)
            before = len(rows)
            cur.execute("select count(*) from pieces")
            pieces_before = (cur.fetchone() or [0])[0]
            cur.execute("select count(*) from events")
            events_before = (cur.fetchone() or [0])[0]

            counts = backfill_intake(cur, rows)
            groups = merge_groups(rows)
            stats = apply_merge(cur, groups)
            primaries = mark_primaries(cur, rows, groups)
            _apply_swap_ddl(conn)

            cur.execute("select count(*) from contacts")
            after = (cur.fetchone() or [0])[0]
            cur.execute("select count(*) from pieces")
            pieces_after = (cur.fetchone() or [0])[0]
            cur.execute("select count(*) from events")
            events_after = (cur.fetchone() or [0])[0]

            merged_rows = sum(len(g["members"]) for g in groups)
            print("\n== merge ==")
            print(f"  intake_cslb_ca rows      {counts['intake_cslb_ca']:>8}")
            print(f"  intake_fbn_ca rows       {counts['intake_fbn_ca']:>8}")
            print(f"  seeds (seed_key, no row) {counts['seeds']:>8}")
            print(f"  phone groups merged      {len(groups):>8}")
            print(f"  rows in those groups     {merged_rows:>8}")
            print(f"  primaries marked         {primaries:>8}")
            print(f"  next-actions merged      {stats['merged_next_actions']:>8}")
            print("\n== before / after ==")
            print(f"  contacts  {before:>8} -> {after:>8}   (delta {after - before:+})")
            print(f"  pieces    {pieces_before:>8} -> {pieces_after:>8}   (must be unchanged)")
            print(f"  events    {events_before:>8} -> {events_after:>8}   (must be unchanged)")
            if pieces_before != pieces_after or events_before != events_after:
                raise PreflightHalt(
                    "pieces/events counts changed — they are repointed, never deleted."
                )
    except PreflightHalt as exc:
        conn.rollback()
        print(f"\nHALT: {exc}", file=sys.stderr)
        return True

    if args.execute:
        conn.commit()
        print("\ncommitted. Next: recompute_state() over all contacts (step 7), then the "
              "verify_addresses backfill (step 9).")
    else:
        conn.rollback()
        print("\nrolled back (dry run). Re-run with --execute to commit.")
    return False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

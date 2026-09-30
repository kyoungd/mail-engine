"""Part 0, step 1: the command that loads a list, so the upload page can go.

It is a thin door over service.contacts.load_list — the counts it prints are the
IntakeReport's, and what loading does stays load_list's (part 1)."""

from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from intake import cslb_ca, fbn_ca
from jobs.intake_cli import main

FIXTURE = Path(__file__).parents[1] / "e2e" / "fixtures" / "cslb-partner-journey.csv"


def _count(owner_url: str, table: str) -> int:
    with psycopg.connect(owner_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table)))
            row = cur.fetchone()
            assert row is not None
            return row[0]


def test_loads_the_file_and_prints_the_four_counts(clean_db, owner_url, capsys):
    assert main([str(FIXTURE), "--source", "cslb-ca"]) == 0

    assert "loaded=6 deduped=0 invalid=0 suppressed=0" in capsys.readouterr().out
    assert _count(owner_url, "intake_cslb_ca") == 6


def test_the_same_file_twice_loads_nothing_the_second_time(clean_db, owner_url, capsys):
    main([str(FIXTURE), "--source", "cslb-ca"])
    contacts = _count(owner_url, "contacts")
    capsys.readouterr()

    assert main([str(FIXTURE), "--source", "cslb-ca"]) == 0

    assert "loaded=0 deduped=6 invalid=0 suppressed=0" in capsys.readouterr().out
    assert _count(owner_url, "intake_cslb_ca") == 6
    assert _count(owner_url, "contacts") == contacts


def test_an_unknown_source_is_refused_and_nothing_is_written(clean_db, owner_url, capsys):
    assert main([str(FIXTURE), "--source", "no-such-source"]) != 0

    err = capsys.readouterr().err
    assert "no-such-source" in err
    assert "cslb-ca" in err  # names the sources it knows
    assert _count(owner_url, "intake_cslb_ca") == 0
    assert _count(owner_url, "contacts") == 0


def test_source_is_required():
    with pytest.raises(SystemExit) as exit_:
        main([str(FIXTURE)])
    assert exit_.value.code != 0


def test_help_gives_usage_and_examples(capsys):
    with pytest.raises(SystemExit) as exit_:
        main(["--help"])
    assert exit_.value.code == 0
    out = capsys.readouterr().out
    assert "--source" in out
    assert "python -m jobs.intake_cli" in out


@pytest.mark.parametrize("converter", [cslb_ca, fbn_ca])
def test_the_converters_help_names_the_command_not_the_web_page(converter, capsys):
    with pytest.raises(SystemExit):
        converter.main(["--help"])
    out = capsys.readouterr().out
    assert "python -m jobs.intake_cli" in out
    assert "web UI" not in out

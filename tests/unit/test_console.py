"""jobs/console.py — the operator's menu front door (2026-08-05). Thin dispatch
over existing verbs; the one load-bearing behavior of its own is the onboarding
walk's compliance ORDER: purchase-pause before subscribe → scrub → assign."""

import json

import pytest

from jobs import console


def _feed(monkeypatch, *answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _="": next(it))


def test_quits_on_zero(monkeypatch, capsys):
    _feed(monkeypatch, "0")
    assert console.main([]) == 0
    assert "partner status" in capsys.readouterr().out  # the menu rendered


def test_dispatches_then_returns_to_menu(monkeypatch, capsys):
    calls = []
    monkeypatch.setitem(
        console.ACTIONS, "1", ("partner status", lambda: calls.append("status") or 0)
    )
    _feed(monkeypatch, "1", "0")
    assert console.main([]) == 0
    assert calls == ["status"]
    assert capsys.readouterr().out.count("partner status") >= 2  # menu shown again


def test_unknown_choice_reprompts_without_crashing(monkeypatch):
    _feed(monkeypatch, "99", "x", "0")
    assert console.main([]) == 0


def _owned_inventory(monkeypatch, *codes):
    monkeypatch.setattr(
        console, "_owned_inventory",
        lambda: [(c, 100, 50, 50) for c in codes],  # code, total, dialable, available
    )


def _steps(monkeypatch, ran):
    monkeypatch.setattr(
        console, "ONBOARD_STEPS",
        [(name, lambda name=name: ran.append(name) or 0)
         for name, _ in console.ONBOARD_STEPS],
    )


def test_onboard_owned_code_skips_the_purchase_pause(monkeypatch):
    ran = []
    _steps(monkeypatch, ran)
    _owned_inventory(monkeypatch, "818")
    _feed(monkeypatch, "818")  # the pick; NO purchase prompt consumed
    assert console.run_onboarding() == 0
    assert ran == ["register", "subscribe", "assign", "export"]  # sync is the cron's job


def test_onboarding_stops_at_pick_when_no_scrubbed_inventory(monkeypatch):
    ran = []
    _steps(monkeypatch, ran)
    monkeypatch.setattr(
        console, "_owned_inventory", lambda: [("818", 6023, 0, 0)]
    )  # owned, never scrubbed (or pool drained)
    _feed(monkeypatch, "818")
    assert console.run_onboarding() != 0
    assert ran == []  # nothing ran; the message points at menu 7


def test_onboarding_of_a_new_code_ends_after_subscribe_with_guidance(monkeypatch, capsys):
    ran = []
    _steps(monkeypatch, ran)
    _owned_inventory(monkeypatch, "818")
    _feed(monkeypatch, "310", "y")  # unowned pick → purchase confirmed
    assert console.run_onboarding() == 0
    assert ran == ["register", "subscribe"]  # sync belongs to the daily cycle
    assert "daily cycle" in capsys.readouterr().out.lower()


def test_onboard_declined_purchase_runs_nothing(monkeypatch):
    ran = []
    _steps(monkeypatch, ran)
    _owned_inventory(monkeypatch, "818")
    _feed(monkeypatch, "310", "n")  # unowned pick → pause → declined
    assert console.run_onboarding() != 0
    assert ran == []  # nothing registered, subscribed, scrubbed, or assigned


def test_a_step_raising_systemexit_stops_the_walk_cleanly(monkeypatch):
    ran = []
    _steps(monkeypatch, ran)
    _owned_inventory(monkeypatch, "818")
    boom = ("assign", lambda: (_ for _ in ()).throw(SystemExit(2)))
    monkeypatch.setattr(
        console, "ONBOARD_STEPS",
        [s if s[0] != "assign" else boom for s in console.ONBOARD_STEPS],
    )
    _feed(monkeypatch, "818")
    assert console.run_onboarding() == 2  # reported as a result, not a process death


def test_a_menu_action_raising_systemexit_returns_to_menu(monkeypatch):
    monkeypatch.setitem(
        console.ACTIONS, "1",
        ("partner status", lambda: (_ for _ in ()).throw(SystemExit(2))),
    )
    _feed(monkeypatch, "1", "0")
    assert console.main([]) == 0  # the console survives the verb's exit


def test_help_is_wired(capsys):
    with pytest.raises(SystemExit) as e:
        console.main(["--help"])
    assert e.value.code == 0
    assert "console" in capsys.readouterr().out


def test_assign_step_carries_the_picked_code_into_the_rule(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "jobs.assignment_cli.main", lambda argv: captured.setdefault("argv", argv) and 0
    )
    monkeypatch.setattr(console, "_picked_code", "818")
    monkeypatch.setattr(console, "_partner_name", "John")
    _feed(monkeypatch, "", "", "")  # accept partner/key defaults, derived count
    console._step_assign()
    rule_json = captured["argv"][captured["argv"].index("--rule") + 1]
    assert json.loads(rule_json) == {"area_code": ["818"]}


def _roster_rows(monkeypatch, *rows):
    monkeypatch.setattr(console, "_roster", lambda: list(rows))


def test_register_step_picks_an_existing_partner_by_number(monkeypatch):
    _roster_rows(monkeypatch, ("John", 3, "JO-01"), ("Steven Kim", None, None))
    monkeypatch.setattr(console, "_partner_hours", lambda name: 10)  # assignable
    _feed(monkeypatch, "2")  # pick by number — no create prompts consumed
    assert console._step_register() == 0
    assert console._partner_name == "Steven Kim"


def test_register_step_creates_new_when_n_chosen(monkeypatch):
    captured = {}
    _roster_rows(monkeypatch, ("John", 3, "JO-01"))
    monkeypatch.setattr(
        "jobs.partners_cli.main", lambda argv: captured.setdefault("argv", argv) and 0
    )
    _feed(monkeypatch, "n", "Steven Kim", "sk@example.com", "10", "4", "SK-01")
    assert console._step_register() == 0
    assert captured["argv"][:2] == ["set", "Steven Kim"]
    assert console._partner_name == "Steven Kim"


def test_assign_from_menu_offers_the_numbered_pick(monkeypatch):
    captured = {}
    _roster_rows(monkeypatch, ("John", 3, "JO-01"), ("Steven Kim", None, None))
    monkeypatch.setattr(
        "jobs.assignment_cli.main", lambda argv: captured.setdefault("argv", argv) and 0
    )
    monkeypatch.setattr(console, "_partner_name", "")  # bare menu use, no walk context
    monkeypatch.setattr(console, "_picked_code", "")
    _feed(monkeypatch, "1", "", "")  # pick John, accept key default, derived count
    console._step_assign()
    assert captured["argv"][1] == "John"


def test_a_step_raising_a_domain_error_stops_the_walk_cleanly(monkeypatch):
    ran = []
    _steps(monkeypatch, ran)
    _owned_inventory(monkeypatch, "818")
    from domain.errors import ValidationError

    boom = ("assign", lambda: (_ for _ in ()).throw(ValidationError("no_hours", "no hours")))
    monkeypatch.setattr(
        console, "ONBOARD_STEPS",
        [s if s[0] != "assign" else boom for s in console.ONBOARD_STEPS],
    )
    _feed(monkeypatch, "818")
    assert console.run_onboarding() != 0  # reported as a result, not a process death


def test_picking_a_partner_without_hours_prompts_and_sets_them(monkeypatch):
    captured = {}
    _roster_rows(monkeypatch, ("John", None, None))
    monkeypatch.setattr(console, "_partner_hours", lambda name: None)
    monkeypatch.setattr(
        "jobs.partners_cli.main", lambda argv: captured.setdefault("argv", argv) and 0
    )
    _feed(monkeypatch, "1", "")  # pick John, accept hours default 10
    assert console._step_register() == 0
    assert captured["argv"] == ["set", "John", "--hours", "10"]


def test_picking_a_partner_with_hours_asks_nothing_more(monkeypatch):
    _roster_rows(monkeypatch, ("John", 3, "JO-01"))
    monkeypatch.setattr(console, "_partner_hours", lambda name: 10)
    _feed(monkeypatch, "1")  # pick consumes the ONLY input
    assert console._step_register() == 0


def test_help_manual_prints_and_returns_to_menu(monkeypatch, capsys):
    _feed(monkeypatch, "11", "0")
    assert console.main([]) == 0
    out = capsys.readouterr().out
    assert "operator manual" in out
    assert "90 days" in out  # the custody clock is in the manual
    assert out.count("mail-engine console") >= 2  # menu re-rendered after help


def test_collected_file_is_picked_from_the_drop_folder_by_number(monkeypatch, tmp_path):
    (tmp_path / "john.csv").write_text("phone\n")
    (tmp_path / "steven.csv").write_text("phone\n")
    monkeypatch.setattr(console, "_COLLECTED", tmp_path)
    _feed(monkeypatch, "2")  # a number, never a path
    assert console._pick_collected_file() == tmp_path / "steven.csv"


def test_collected_file_accepts_a_bare_filename(monkeypatch, tmp_path):
    (tmp_path / "john.csv").write_text("phone\n")
    monkeypatch.setattr(console, "_COLLECTED", tmp_path)
    _feed(monkeypatch, "john.csv")
    assert console._pick_collected_file() == tmp_path / "john.csv"


def test_an_empty_drop_folder_says_where_the_file_goes(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(console, "_COLLECTED", tmp_path)
    assert console._pick_collected_file() is None
    assert str(tmp_path) in capsys.readouterr().out

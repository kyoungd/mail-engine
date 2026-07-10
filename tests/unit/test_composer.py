"""Unit tests for the composer: template shape and the fallback contract (no DB)."""

from uuid import uuid4

from judgment.composer import compose_brief, template_brief
from judgment.protocol import Hit
from judgment.rules.hot_response import RULE as hot_response


def _hit():
    return Hit(contact_id=uuid4(), wave_id=None)


def test_template_brief_names_the_rule_and_target():
    brief = template_brief(_hit(), hot_response)
    assert brief.startswith("[hot_response]")
    assert "contact" in brief


def test_no_client_uses_the_template():
    hit = _hit()
    assert compose_brief(hit, [], hot_response, None) == template_brief(hit, hot_response)


def test_failing_client_falls_back_to_template():
    class _Fail:
        def complete(self, prompt):
            raise RuntimeError("boom")

    hit = _hit()
    assert compose_brief(hit, [], hot_response, _Fail()) == template_brief(hit, hot_response)


def test_empty_completion_falls_back_to_template():
    class _Empty:
        def complete(self, prompt):
            return "   "

    hit = _hit()
    assert compose_brief(hit, [], hot_response, _Empty()) == template_brief(hit, hot_response)


def test_a_real_completion_is_used_verbatim():
    class _Ok:
        def complete(self, prompt):
            return "a real brief"

    assert compose_brief(_hit(), [], hot_response, _Ok()) == "a real brief"

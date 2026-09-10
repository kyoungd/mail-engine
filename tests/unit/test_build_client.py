"""The client bake: one rep's identity into one artifact.

A build that silently failed to substitute would ship a program that refuses at
startup in a rep's hands — recoverable, but only after a support call.
"""

import pytest

from scripts.build_client import BakeError, bake

SOURCE = 'BAKED_TOKEN = ""\nBAKED_UPLOAD_URL = ""\nprint("hi")\n'


def test_bake_replaces_both_constants():
    out = bake(SOURCE, token="nmcdnc_abc", upload_url="https://dnc.example")

    assert 'BAKED_TOKEN = "nmcdnc_abc"' in out
    assert 'BAKED_UPLOAD_URL = "https://dnc.example"' in out
    assert 'BAKED_TOKEN = ""' not in out


def test_bake_refuses_when_the_placeholders_are_gone():
    with pytest.raises(BakeError):
        bake('BAKED_TOKEN = "already"\n', token="t", upload_url="u")


def test_bake_refuses_an_empty_token():
    with pytest.raises(BakeError):
        bake(SOURCE, token="", upload_url="https://dnc.example")


def test_bake_refuses_a_value_that_would_break_out_of_the_string():
    with pytest.raises(BakeError):
        bake(SOURCE, token='a" + evil() + "', upload_url="https://dnc.example")

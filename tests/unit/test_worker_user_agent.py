"""Cloudflare's edge refuses Python's default User-Agent (error 1010) before the
upload Worker runs — measured 2026-09-10 against the live Worker: the same request
answered 403/1010 as `Python-urllib/3.12` and 200 under any named agent. Every real
transport that talks to the Worker must therefore name itself."""

import io
import urllib.request

import pytest

from clients import dnc_uploader
from seams import snapshot_inbox, token_registry


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def sent(monkeypatch):
    requests = []

    def urlopen(request, timeout=None):
        requests.append(request)
        return _Response(b'{"objects": [], "truncated": false}')

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return requests


def _assert_named(request):
    agent = request.get_header("User-agent") or ""
    assert agent, "no User-Agent: urllib sends Python-urllib/x.y, which Cloudflare refuses"
    assert not agent.lower().startswith("python-urllib")


def test_token_publish_names_itself(sent):
    token_registry._default_transport(
        "PUT", "https://dnc.example/admin/tokens/ab", {"Authorization": "Bearer t"},
        {"partner_id": "p"},
    )
    _assert_named(sent[0])


def test_inbox_listing_names_itself(sent):
    snapshot_inbox._default_transport("https://dnc.example/pending", {"Authorization": "Bearer t"})
    _assert_named(sent[0])


def test_inbox_fetch_names_itself(sent, tmp_path):
    snapshot_inbox._default_transport(
        "https://dnc.example/object/dnc%2Fx.zip", {"Authorization": "Bearer t"}, tmp_path / "x.zip"
    )
    _assert_named(sent[0])


def test_uploader_names_itself(sent, tmp_path):
    upload = tmp_path / "2026-9-10_818_x.txt.zip"
    upload.write_bytes(b"zip")
    dnc_uploader._default_transport("https://dnc.example/upload/x", {"X-API-KEY": "t"}, upload)
    _assert_named(sent[0])

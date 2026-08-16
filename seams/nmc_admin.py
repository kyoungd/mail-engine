"""The main-site admin seam (console login gate + sales-rep registration,
approved 2026-08-16). Two calls against the local Medusa web app:

  POST {NMC_WEB_URL}/auth/customer/emailpass          -> {"token": <JWT>}
  GET/POST {NMC_WEB_URL}/store/nmc/admin/sales-reps   -> the roster (admin-only)

Every /store/* request carries `x-publishable-api-key` (`NMC_PUBLISHABLE_KEY`,
Medusa's public client key) or Medusa refuses before auth runs. The admin check
is the server's: a valid customer JWT whose email is in ADMIN_EMAILS. 401 and
403 are DIFFERENT failures (bad credentials vs not an admin) and stay distinct
here. Rep ids arrive as strings (the BigInt-as-string wire convention) and are
returned unconverted.
"""

import json
import os
import urllib.error
import urllib.request

_TIMEOUT_SECONDS = 10.0


class NmcAdminError(Exception):
    pass


class NmcAdminConfigError(NmcAdminError):
    pass


class NmcAuthError(NmcAdminError):
    pass


class NmcNotAdminError(NmcAdminError):
    pass


def _urllib_transport(method, url, body, headers):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}


class NmcAdminClient:
    def __init__(self, base_url, publishable_key=None, transport=None):
        if not base_url:
            raise NmcAdminConfigError("NMC_WEB_URL is not set")
        if not publishable_key:
            raise NmcAdminConfigError("NMC_PUBLISHABLE_KEY is not set")
        self.base_url = base_url.rstrip("/")
        self.publishable_key = publishable_key
        self.transport = transport or _urllib_transport

    @classmethod
    def from_env(cls) -> "NmcAdminClient":
        return cls(
            os.environ.get("NMC_WEB_URL", ""),
            os.environ.get("NMC_PUBLISHABLE_KEY", ""),
        )

    def _store_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "x-publishable-api-key": self.publishable_key,
            "Content-Type": "application/json",
        }

    def login(self, email: str, password: str) -> str:
        status, payload = self.transport(
            "POST",
            f"{self.base_url}/auth/customer/emailpass",
            {"email": email, "password": password},
            {"Content-Type": "application/json"},
        )
        if status == 401:
            raise NmcAuthError("credentials rejected (401) — check email/password")
        if status != 200:
            raise NmcAdminError(f"login failed (HTTP {status})")
        return payload["token"]

    @staticmethod
    def _check_store_status(status: int, action: str) -> None:
        if status == 401:
            raise NmcAuthError("session rejected (401) — log in again")
        if status == 403:
            raise NmcNotAdminError(
                "logged in, but not an admin — the account is not in the "
                "main site's ADMIN_EMAILS"
            )
        if status != 200:
            raise NmcAdminError(f"{action} failed (HTTP {status})")

    def verify_admin(self, token: str) -> None:
        self.list_sales_reps(token)

    def list_sales_reps(self, token: str) -> list[dict]:
        status, payload = self.transport(
            "GET",
            f"{self.base_url}/store/nmc/admin/sales-reps",
            None,
            self._store_headers(token),
        )
        self._check_store_status(status, "admin check")
        return payload["reps"]

    def create_sales_rep(self, token: str, *, email: str, name: str) -> str:
        status, payload = self.transport(
            "POST",
            f"{self.base_url}/store/nmc/admin/sales-reps",
            {"email": email, "name": name},
            self._store_headers(token),
        )
        self._check_store_status(status, "sales-rep create")
        return payload["rep"]["id"]

"""Small client for the website's desktop-app API (login, balance, charging and refunds)."""

import json
import urllib.error
import urllib.request

from . import APP_VERSION
from .i18n import tr


class ApiError(Exception):
    def __init__(self, message, code="error", status=0):
        super().__init__(message)
        self.code = code
        self.status = status


class ApiClient:
    def __init__(self, base_url, token="", language="fa"):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.language = language

    def _request(self, method, path, data=None, timeout=20):
        body = json.dumps(data).encode() if data is not None else None
        headers = {
            "Accept": "application/json",
            "Accept-Language": self.language,
            "User-Agent": f"MediaEnhancerDesktop/{APP_VERSION}",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        req = urllib.request.Request(f"{self.base_url}/api/app/{path}", data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                raise ApiError(payload.get("error") or str(exc), payload.get("code", "error"), exc.code) from None
            except ValueError:
                raise ApiError(tr("server_error", status=exc.code), "error", exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ApiError(tr("network_error"), "network") from exc
        except ValueError as exc:
            raise ApiError(tr("server_error", status="?"), "error") from exc

    def login(self, username, password, device=""):
        data = self._request("POST", "login/", {"username": username, "password": password, "device": device})
        self.token = data["token"]
        return data["account"]

    def logout(self):
        try:
            self._request("POST", "logout/", {})
        finally:
            self.token = ""

    def me(self):
        return self._request("GET", "me/")["account"]

    def start_job(self, **job):
        return self._request("POST", "jobs/", {**job, "app_version": APP_VERSION})

    def finish_job(self, job_id, status, seconds=0, error=""):
        return self._request("POST", f"jobs/{job_id}/finish/", {"status": status, "seconds": seconds, "error": error})

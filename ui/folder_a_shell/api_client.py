"""HTTP client for the REST API.

- base URL, timeout, token file and mock mode come from .env (UI_*)
- the JWT pair is stored in the user's home directory and sent as a Bearer header
- a 401 triggers one refresh attempt; if that fails the session is cleared and
  `on_session_expired` is called (the shell returns to the login screen)
- UI_MOCK_MODE=true serves responses recorded from a real API run (ui/fixtures/), never invented data
"""
from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import requests

from config.loader import ROOT, env, env_bool


class ApiError(Exception):
    def __init__(self, status: int, detail: str, code: str = "", data: Any = None):
        super().__init__(detail)
        self.status, self.detail, self.code, self.data = status, detail, code, data or {}

    def __str__(self):
        return self.detail


class SessionExpired(ApiError):
    pass


def _token_path() -> Path:
    p = Path(env("UI_TOKEN_FILE"))
    return p if p.is_absolute() else Path.home() / p


class ApiClient:
    def __init__(self):
        self.base = env("UI_API_BASE_URL").rstrip("/")
        self.timeout = env("UI_HTTP_TIMEOUT_SECONDS", cast=float)
        self.on_session_expired: Callable[[], None] | None = None
        self.user: dict | None = None
        self._lock = threading.Lock()
        self._tokens = self._load_tokens()
        self.http = requests.Session()

    # ------------------------------------------------------------------ tokens
    def _load_tokens(self) -> dict:
        try:
            return json.loads(_token_path().read_text())
        except (OSError, ValueError):
            return {}

    def _save_tokens(self) -> None:
        p = _token_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self._tokens))
        try:
            p.chmod(0o600)
        except OSError:
            pass

    def clear_session(self) -> None:
        self._tokens, self.user = {}, None
        try:
            _token_path().unlink()
        except OSError:
            pass

    @property
    def has_session(self) -> bool:
        return bool(self._tokens.get("refresh"))

    # ------------------------------------------------------------------ core
    def url(self, path: str) -> str:
        return path if path.startswith("http") else f"{self.base}/{path.lstrip('/')}"

    def media_url(self, path: str | None) -> str | None:
        if not path:
            return None
        if path.startswith("http"):
            return path
        root = self.base.rsplit("/api", 1)[0]
        return f"{root}{path}"

    def _send(self, method, path, *, params=None, json_body=None, files=None, data=None, headers=None, auth=True):
        h = dict(headers or {})
        if auth and self._tokens.get("access"):
            h["Authorization"] = f"Bearer {self._tokens['access']}"
        try:
            return self.http.request(method, self.url(path), params=params, json=json_body, files=files, data=data,
                                     headers=h, timeout=self.timeout)
        except requests.ConnectionError:
            raise ApiError(0, f"Cannot reach the API at {self.base}. Is 'python store.py api' running?", "offline")
        except requests.Timeout:
            raise ApiError(0, "The server took too long to respond.", "timeout")

    def _refresh(self) -> bool:
        with self._lock:
            refresh = self._tokens.get("refresh")
            if not refresh:
                return False
            r = self._send("POST", "auth/refresh/", json_body={"refresh": refresh}, auth=False)
            if r.status_code != 200:
                return False
            self._tokens["access"] = r.json()["access"]
            if "refresh" in r.json():
                self._tokens["refresh"] = r.json()["refresh"]
            self._save_tokens()
            return True

    def request(self, method: str, path: str, *, raw: bool = False, **kw):
        r = self._send(method, path, **kw)
        if r.status_code == 401 and kw.get("auth", True) and self._tokens.get("refresh"):
            if self._refresh():
                r = self._send(method, path, **kw)
            else:
                self.clear_session()
                if self.on_session_expired:
                    self.on_session_expired()
                raise SessionExpired(401, "Your session has expired. Please sign in again.", "session_expired")
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = {"detail": r.text[:200] or r.reason}
            detail = body.get("detail") or "Request failed"
            if body.get("errors"):
                detail = "; ".join(f"{k}: {' '.join(v) if isinstance(v, list) else v}" for k, v in body["errors"].items())
            raise ApiError(r.status_code, str(detail), body.get("code", ""), body)
        if raw:
            return r.content
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    def get(self, path, params=None, **kw):
        return self.request("GET", path, params=params, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, json_body=body, **kw)

    def patch(self, path, body=None, **kw):
        return self.request("PATCH", path, json_body=body, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    def upload(self, path, file_path: str, field="image", extra: dict | None = None):
        with open(file_path, "rb") as fh:
            return self.request("POST", path, files={field: (Path(file_path).name, fh)}, data=extra or {})

    def download(self, path, params=None) -> bytes:
        return self.request("GET", path, params=params, raw=True)

    def fetch_bytes(self, url: str) -> bytes | None:
        try:
            r = self.http.get(self.media_url(url), timeout=self.timeout)
            return r.content if r.ok else None
        except requests.RequestException:
            return None

    # ------------------------------------------------------------------ auth
    def login(self, email: str, password: str) -> dict:
        data = self.request("POST", "auth/login/", json_body={"email": email, "password": password}, auth=False)
        self._tokens = {"access": data["access"], "refresh": data["refresh"]}
        self._save_tokens()
        self.user = data["user"]
        return self.user

    def register(self, **fields) -> dict:
        return self.request("POST", "auth/register/", json_body=fields, auth=False)

    def restore_session(self) -> dict | None:
        if not self.has_session:
            return None
        try:
            self.user = self.get("auth/me/")
            return self.user
        except ApiError:
            self.clear_session()
            return None

    def logout(self) -> None:
        self.clear_session()


FIXTURE_DIR = ROOT / "ui" / "fixtures"


def fixture_key(method: str, path: str, params: dict | None) -> str:
    q = urlencode(sorted((k, str(v)) for k, v in (params or {}).items() if v not in (None, "")))
    return f"{method} {path.strip('/')}" + (f"?{q}" if q else "")


class MockApiClient(ApiClient):
    """Replays responses recorded from a real API run (python -m ui.folder_a_shell.record_fixtures)."""

    def __init__(self):
        super().__init__()
        index = FIXTURE_DIR / "index.json"
        if not index.exists():
            raise RuntimeError("UI_MOCK_MODE is on but ui/fixtures/index.json is missing. Generate fixtures with "
                               "'python -m ui.folder_a_shell.record_fixtures' while the API is running.")
        self.fixtures = json.loads(index.read_text())
        self.role_set = None

    def request(self, method, path, *, raw=False, params=None, json_body=None, **kw):
        if path.strip("/") == "auth/login/".strip("/"):
            for role, data in self.fixtures["roles"].items():
                if data["user"]["email"] == (json_body or {}).get("email"):
                    self.role_set, self.user = role, data["user"]
                    return {"access": "mock", "refresh": "mock", "user": data["user"]}
            raise ApiError(401, "Mock mode: use one of the recorded demo accounts.", "mock")
        if self.role_set is None:
            raise SessionExpired(401, "Not signed in (mock mode).", "mock")
        responses = self.fixtures["roles"][self.role_set]["responses"]
        key = fixture_key(method, path, params)
        if key not in responses:
            raise ApiError(503, "Not available in mock mode (no recorded response).", "mock_missing")
        return responses[key]

    def login(self, email, password):
        data = self.request("POST", "auth/login/", json_body={"email": email, "password": password})
        return data["user"]

    def restore_session(self):
        return None

    def _save_tokens(self):
        pass

    def fetch_bytes(self, url):
        p = FIXTURE_DIR / "media" / url.lstrip("/").replace("/", "_")
        return p.read_bytes() if p.exists() else None


def make_client() -> ApiClient:
    return MockApiClient() if env_bool("UI_MOCK_MODE", False) else ApiClient()


class RecordingApiClient(ApiClient):
    """Real client that also records every GET response per account into ui/fixtures/ (for MOCK_MODE)."""

    def __init__(self):
        super().__init__()
        self.recorded: dict = {"roles": {}}
        # A new recording replaces the old one, so drop images that the new index won't reference
        shutil.rmtree(FIXTURE_DIR / "media", ignore_errors=True)
        (FIXTURE_DIR / "media").mkdir(parents=True, exist_ok=True)

    def _bucket(self):
        email = (self.user or {}).get("email")
        if not email:
            return None
        return self.recorded["roles"].setdefault(email, {"user": self.user, "responses": {}})

    def request(self, method, path, *, raw=False, **kw):
        data = super().request(method, path, raw=raw, **kw)
        bucket = self._bucket()
        if bucket is not None and method == "GET" and not raw:
            bucket["responses"][fixture_key(method, path, kw.get("params"))] = data
        return data

    def login(self, email, password):
        user = super().login(email, password)
        self._bucket()
        return user

    def fetch_bytes(self, url):
        data = super().fetch_bytes(url)
        if data:
            (FIXTURE_DIR / "media" / url.lstrip("/").replace("/", "_")).write_bytes(data)
        return data

    def save(self):
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        (FIXTURE_DIR / "index.json").write_text(json.dumps(self.recorded, indent=1, default=str))

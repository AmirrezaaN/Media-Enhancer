"""User settings, saved as JSON in %APPDATA%\\MediaEnhancer.

The login token is encrypted with Windows DPAPI, so it can only be read by the same Windows user.
"""

import base64
import ctypes
import json
import logging
import sys
from ctypes import wintypes

from .paths import ensure_data_dir

logger = logging.getLogger("desktop")

DEFAULTS = {
    "server_url": "http://127.0.0.1:8000",
    "language": "en",
    "output_dir": "",
    "username": "",
    "token": "",
    "pending_reports": [],
}


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def encrypt(text: str) -> str:
    if not text:
        return ""
    if sys.platform != "win32":
        return base64.b64encode(text.encode()).decode()
    return base64.b64encode(_dpapi(text.encode(), True)).decode()


def decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        raw = base64.b64decode(value)
        return (_dpapi(raw, False) if sys.platform == "win32" else raw).decode()
    except (OSError, ValueError):
        return ""


class Settings:
    def __init__(self):
        self.path = ensure_data_dir() / "settings.json"
        self.data = dict(DEFAULTS)
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        self.data[key] = value
        self.save()

    @property
    def token(self) -> str:
        return decrypt(self.data.get("token", ""))

    @token.setter
    def token(self, value: str):
        self.data["token"] = encrypt(value)
        self.save()

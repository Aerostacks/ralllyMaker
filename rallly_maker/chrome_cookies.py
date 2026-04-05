"""Decrypt Google-domain cookies from a real Chrome profile on Linux."""

import hashlib
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

COOKIE_DB = Path.home() / ".config/google-chrome/Default/Cookies"
GOOGLE_HOSTS = ("%google.com", "%googleusercontent.com", "%gstatic.com")


def _get_secret() -> bytes:
    out = subprocess.check_output(
        ["secret-tool", "search", "application", "chrome"], text=True
    )
    for line in out.splitlines():
        if line.startswith("secret = "):
            return line.split("=", 1)[1].strip().encode()
    raise RuntimeError("Chrome Safe Storage secret not found")


def _decrypt(secret: bytes, host_key: str, encrypted_value: bytes) -> str:
    if not encrypted_value:
        return ""
    if encrypted_value[:3] in (b"v10", b"v11"):
        key = hashlib.pbkdf2_hmac("sha1", secret, b"saltysalt", 1, dklen=16)
        dec = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
        pt = dec.update(encrypted_value[3:]) + dec.finalize()
        pt = pt[: -pt[-1]]  # strip PKCS7 padding
        # Chrome may prepend SHA256(host_key) to the plaintext
        digest = hashlib.sha256(host_key.encode()).digest()
        if pt.startswith(digest):
            pt = pt[len(digest) :]
        return pt.decode("utf-8", errors="ignore")
    return encrypted_value.decode("utf-8", errors="ignore")


def get_google_cookies(host_patterns=GOOGLE_HOSTS) -> list[dict]:
    """Return list of cookie dicts (name, value, domain, path, secure, httpOnly)."""
    secret = _get_secret()
    tmp = Path(tempfile.mkdtemp(prefix="chrome-cookies-"))
    db_copy = tmp / "Cookies"
    shutil.copy2(COOKIE_DB, db_copy)
    conn = sqlite3.connect(str(db_copy))
    placeholders = " OR ".join("host_key LIKE ?" for _ in host_patterns)
    rows = conn.execute(
        f"SELECT host_key, name, path, expires_utc, is_secure, is_httponly, encrypted_value, value FROM cookies WHERE {placeholders}",
        host_patterns,
    ).fetchall()
    conn.close()
    cookies = []
    for host_key, name, path, expires_utc, is_secure, is_httponly, enc, val in rows:
        decrypted = val or _decrypt(secret, host_key, enc)
        if not decrypted:
            continue
        c = {
            "name": name,
            "value": decrypted,
            "domain": host_key,
            "path": path,
            "secure": bool(is_secure),
            "httpOnly": bool(is_httponly),
        }
        if expires_utc and expires_utc > 0:
            unix_ts = int(expires_utc / 1_000_000 - 11_644_473_600)
            if unix_ts > 0:
                c["expires"] = unix_ts
        cookies.append(c)
    return cookies


def cookies_as_requests_jar(cookies: list[dict]):
    """Convert cookie list to a requests-compatible CookieJar."""
    import requests.cookies

    jar = requests.cookies.RequestsCookieJar()
    for c in cookies:
        jar.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
    return jar

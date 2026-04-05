"""Minimal Chrome DevTools Protocol client over websocket."""

import json
import subprocess
import threading
import time

import websocket


class CdpClient:
    def __init__(self, ws_url: str):
        self._ws = websocket.WebSocket()
        self._ws.connect(ws_url)
        self._next_id = 1
        self._pending: dict[int, dict] = {}
        self._events: list[dict] = []
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        while True:
            try:
                data = self._ws.recv()
                if not data:
                    break
                msg = json.loads(data)
                with self._lock:
                    if "id" in msg and msg["id"] in self._pending:
                        self._pending[msg["id"]] = msg
                    else:
                        self._events.append(msg)
            except Exception:
                break

    def send(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        mid = self._next_id
        self._next_id += 1
        with self._lock:
            self._pending[mid] = None
        self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._pending[mid] is not None:
                    result = self._pending.pop(mid)
                    if "error" in result:
                        raise RuntimeError(result["error"])
                    return result.get("result", {})
            time.sleep(0.05)
        raise TimeoutError(f"CDP call {method} timed out")

    def wait_event(self, method: str, timeout: float = 20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                for i, ev in enumerate(self._events):
                    if ev.get("method") == method:
                        return self._events.pop(i).get("params")
            time.sleep(0.1)
        return None

    def evaluate(self, expression: str, timeout: float = 30):
        r = self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        }, timeout=timeout)
        return r.get("result", {}).get("value")

    def navigate(self, url: str, wait: float = 3):
        self.send("Page.navigate", {"url": url})
        self.wait_event("Page.loadEventFired", timeout=20)
        time.sleep(wait)

    def close(self):
        self._ws.close()


def launch_chrome(wrapper_dir: str, debug_port: int = 9222, extra_args: list | None = None) -> subprocess.Popen:
    args = [
        "/usr/bin/google-chrome",
        "--no-sandbox",
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={wrapper_dir}",
        "--profile-directory=Default",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--remote-allow-origins=*",
        "about:blank",
    ]
    if extra_args:
        args.extend(extra_args)
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for_devtools(port: int = 9222, timeout: float = 30) -> str:
    """Wait for Chrome DevTools and return the first page's websocket URL."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list").read()
            pages = json.loads(data)
            for p in pages:
                if p.get("type") == "page" and p.get("webSocketDebuggerUrl"):
                    return p["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.25)
    raise TimeoutError("Chrome DevTools not available")


def inject_cookies(client: CdpClient, cookies: list[dict]):
    """Clear browser cookies and inject the given list."""
    client.send("Network.enable")
    client.send("Network.clearBrowserCookies")
    client.send("Network.setCookies", {"cookies": cookies})

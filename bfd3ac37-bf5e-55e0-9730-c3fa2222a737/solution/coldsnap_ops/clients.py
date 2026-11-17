"""API clients: HTTP against the live SCADA sidecar, or in-process against a virtual session."""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request


class HttpClient:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return self._open(urllib.request.Request(url))

    def _open(self, req) -> dict:
        for attempt in range(30):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                body = exc.read()
                try:
                    detail = json.loads(body)
                except ValueError:
                    detail = {"error": body.decode(errors="replace")}
                raise RuntimeError(f"HTTP {exc.code}: {detail}") from None
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(2.0)
        raise RuntimeError("SCADA API unreachable")

    def status(self) -> dict:
        return self._get("/api/v1/status")

    def forecast(self) -> dict:
        return self._get("/api/v1/forecast")

    def telemetry(self, from_hour: float = 0.0) -> dict:
        return self._get("/api/v1/telemetry", {"from_hour": from_hour})

    def events(self, from_hour: float = 0.0) -> dict:
        return self._get("/api/v1/events", {"from_hour": from_hour})

    def raw(self, tags: list[str], start_hour: float) -> dict:
        return self._get(
            "/api/v1/raw", {"tags": ",".join(tags), "start_hour": start_hour}
        )

    def control(self, change: dict) -> dict:
        req = urllib.request.Request(
            self.base + "/api/v1/control",
            data=json.dumps(change).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._open(req)

    def wait_until(self, hour: float) -> float:
        while True:
            now = self.status()["plant_hour"]
            if now >= hour:
                return now
            time.sleep(min(30.0, max(1.0, (hour - now) * 150.0)))


class VirtualClient:
    """Drives a plantsim Session in virtual time (seed admission and build proofs)."""

    def __init__(self, session):
        self.s = session

    def _call(self, op: str, params: dict | None = None) -> dict:
        return self.s.call(op, params or {})

    def status(self) -> dict:
        return self._call("status")

    def forecast(self) -> dict:
        return self._call("forecast")

    def telemetry(self, from_hour: float = 0.0) -> dict:
        return self._call("telemetry", {"from_hour": from_hour})

    def events(self, from_hour: float = 0.0) -> dict:
        return self._call("events", {"from_hour": from_hour})

    def raw(self, tags: list[str], start_hour: float) -> dict:
        return self._call("raw", {"tags": tags, "start_hour": start_hour})

    def control(self, change: dict) -> dict:
        return self._call("control", change)

    def wait_until(self, hour: float) -> float:
        self.s.set_virtual(int(math.ceil(hour * 360.0 - 1e-9)))
        return self.status()["plant_hour"]

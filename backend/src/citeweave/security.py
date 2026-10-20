"""Access control and bounded in-process admission for one GPU worker."""

import ipaddress
import secrets
import threading
import time
from collections import OrderedDict, deque

from starlette.responses import JSONResponse

from . import config


class RequestLimiter:
    def __init__(self, limit=10, window=60, clients=1024):
        self.limit, self.window, self.clients = limit, window, clients
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, identity):
        now = time.monotonic()
        with self.lock:
            events = self.entries.pop(identity, deque())
            while events and events[0] <= now - self.window:
                events.popleft()
            allowed = len(events) < self.limit
            if allowed:
                events.append(now)
            self.entries[identity] = events
            while len(self.entries) > self.clients:
                self.entries.popitem(last=False)
            return allowed


def authorized(request):
    token = config.ACCESS_TOKEN
    if not token:
        try:
            return ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            return request.client.host == "testclient"
    supplied = request.headers.get("authorization", "")
    supplied = supplied[7:] if supplied.lower().startswith("bearer ") else ""
    return any(
        secrets.compare_digest(value.encode(), token.encode())
        for value in (supplied, request.cookies.get("citeweave_session", ""))
    )


def denied(message, status=401):
    return JSONResponse({"detail": message}, status_code=status)

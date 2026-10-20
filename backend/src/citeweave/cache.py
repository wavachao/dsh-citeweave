"""Bounded SQLite answer cache. Web results expire; source files stay separate."""

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager


class AnswerCache:
    def __init__(self, path, ttl=900, limit=256):
        self.path, self.ttl, self.limit = path, ttl, limit

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS answers (key TEXT PRIMARY KEY, created REAL, body TEXT)"
        )
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def key(parameters):
        return hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()

    def get(self, key):
        if self.ttl <= 0:
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT created, body FROM answers WHERE key=?", (key,)
            ).fetchone()
        if row is None or time.time() - row[0] >= self.ttl:
            return None
        return json.loads(row[1])

    def put(self, key, answer):
        if self.ttl <= 0:
            return
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO answers VALUES (?, ?, ?)",
                (key, time.time(), json.dumps(answer, ensure_ascii=False)),
            )
            connection.execute("DELETE FROM answers WHERE created < ?", (time.time() - self.ttl,))
            connection.execute(
                "DELETE FROM answers WHERE key NOT IN "
                "(SELECT key FROM answers ORDER BY created DESC LIMIT ?)",
                (self.limit,),
            )

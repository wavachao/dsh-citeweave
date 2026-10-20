"""Budgeted DeepSeek proxy for the pinned evaluator; never an official judge.

Serial reservations cover the service-reported context and a 8,192-token output
at peak, cache-miss prices. Unknown/failed calls retain their full reservation.
"""

import asyncio
import json
import os
import runpy
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

MODEL = "deepseek-flash"
CONTEXT_LIMIT = 1_048_576  # Authenticated /models metadata, 2026-10-19.
MAX_OUTPUT = 8192
INPUT_RATE = Decimal("0.3") / 1_000_000
OUTPUT_RATE = Decimal("1.2") / 1_000_000
RESERVATION = INPUT_RATE * CONTEXT_LIMIT + OUTPUT_RATE * MAX_OUTPUT


class BudgetExceeded(BaseException):
    """Fatal control flow: upstream retry handlers must not retry budget refusal."""


class Budget:
    def __init__(self, path, limit_usd, max_requests=10000):
        self.path = Path(path)
        self.limit = Decimal(str(limit_usd))
        self.max_requests = int(max_requests)
        if not self.limit.is_finite() or self.limit <= 0 or self.max_requests < 1:
            raise ValueError("Require a finite positive USD budget and request limit")

    def begin(self, blocking=True):
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = self.path.open("a+")
        try:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            file.seek(0)
            content = file.read()
            state = (
                json.loads(content)
                if content
                else {
                    "scope": "deepseek_proxy_budget_not_official_scores",
                    "limit_usd": str(self.limit),
                    "max_requests": self.max_requests,
                    "price_snapshot": "2026-10-19 peak USD; cache misses assumed",
                    "reservation_per_call_usd": str(RESERVATION),
                    "spent_upper_bound_usd": "0",
                    "calls": [],
                }
            )
            if (
                Decimal(state["limit_usd"]) != self.limit
                or state["max_requests"] != self.max_requests
                or Decimal(state["reservation_per_call_usd"]) != RESERVATION
            ):
                raise ValueError("Budget profile changed; do not reset an existing spending ledger")
            spent = Decimal(state["spent_upper_bound_usd"])
            if len(state["calls"]) >= self.max_requests or spent + RESERVATION > self.limit:
                raise BudgetExceeded("DeepSeek proxy budget/request limit reached; no request sent")
            state["spent_upper_bound_usd"] = str(spent + RESERVATION)
            state["calls"].append(
                {
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "status": "reserved_or_unknown",
                    "reserved_usd": str(RESERVATION),
                }
            )
            self.write(file, state)  # Persist before the network; crashes retain the reservation.
            return file, state
        except BaseException:
            file.close()
            raise

    @staticmethod
    def write(file, state):
        file.seek(0)
        file.truncate()
        json.dump(state, file, indent=2)
        file.flush()
        os.fsync(file.fileno())

    def finish(self, lease, response=None, error=None):
        file, state = lease
        try:
            row = state["calls"][-1]
            if response is not None and response.usage is not None:
                usage = response.usage
                if not (
                    0 <= usage.prompt_tokens <= CONTEXT_LIMIT
                    and 0 <= usage.completion_tokens <= MAX_OUTPUT
                ):
                    raise ValueError("Provider usage exceeds the reserved model/output limits")
                cost = INPUT_RATE * usage.prompt_tokens + OUTPUT_RATE * usage.completion_tokens
                state["spent_upper_bound_usd"] = str(
                    Decimal(state["spent_upper_bound_usd"]) - RESERVATION + cost
                )
                row.update(
                    status="usage_recorded",
                    requested_model=MODEL,
                    returned_model=response.model,
                    system_fingerprint=getattr(response, "system_fingerprint", None),
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    peak_cache_miss_cost_usd=str(cost),
                    finish_reason=response.choices[0].finish_reason,
                )
            else:
                row["error_type"] = error or "MissingUsage"
            self.write(file, state)
        finally:
            file.close()  # Releases the cross-process lock, including for async calls.


def request_options(resource, kwargs):
    if urlsplit(str(resource._client.base_url)).hostname != "api.deepseek.com":
        raise ValueError("Proxy evaluation is restricted to the official DeepSeek endpoint")
    if kwargs.get("model") != MODEL or kwargs.get("stream", False) or kwargs.get("n", 1) != 1:
        raise ValueError("Proxy requires deepseek-flash, nonstreaming and one completion")
    result = dict(kwargs)
    result.pop("n", None)
    result.pop("max_completion_tokens", None)
    result["max_tokens"] = MAX_OUTPUT
    result["extra_body"] = {**(result.get("extra_body") or {}), "thinking": {"type": "disabled"}}
    return result


@contextmanager
def guarded_clients(budget):
    from openai import AsyncOpenAI, OpenAI
    from openai.resources.chat.completions import AsyncCompletions, Completions

    sync_create, async_create = Completions.create, AsyncCompletions.create
    sync_init, async_init = OpenAI.__init__, AsyncOpenAI.__init__

    def initialize(original):
        def init(self, *args, **kwargs):
            kwargs.update(max_retries=0, timeout=60)
            original(self, *args, **kwargs)

        return init

    def create(self, *args, **kwargs):
        options = request_options(self, kwargs)
        lease = budget.begin()
        try:
            response = sync_create(self, *args, **options)
        except BaseException as error:
            budget.finish(lease, error=type(error).__name__)
            raise
        budget.finish(lease, response)
        if response.usage is None or response.choices[0].finish_reason != "stop":
            raise RuntimeError("Proxy judge did not return a complete, metered answer")
        return response

    async def acreate(self, *args, **kwargs):
        options = request_options(self, kwargs)
        while True:
            try:
                lease = budget.begin(blocking=False)
                break
            except BlockingIOError:
                await asyncio.sleep(0.05)
        try:
            response = await async_create(self, *args, **options)
        except BaseException as error:
            budget.finish(lease, error=type(error).__name__)
            raise
        budget.finish(lease, response)
        if response.usage is None or response.choices[0].finish_reason != "stop":
            raise RuntimeError("Proxy judge did not return a complete, metered answer")
        return response

    with (
        patch.object(OpenAI, "__init__", initialize(sync_init)),
        patch.object(AsyncOpenAI, "__init__", initialize(async_init)),
        patch.object(Completions, "create", create),
        patch.object(AsyncCompletions, "create", acreate),
    ):
        yield


def main():
    root = Path(__file__).resolve().parents[1]
    budget = Budget(
        os.environ["CITEWEAVE_PROXY_BUDGET_FILE"], os.environ["CITEWEAVE_PROXY_BUDGET_USD"]
    )
    sys.argv[0] = str(root / "reference/M2RAG/evaluate.py")
    try:
        with guarded_clients(budget):
            runpy.run_path(sys.argv[0], run_name="__main__")
    except BudgetExceeded as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(75) from None


if __name__ == "__main__":
    main()

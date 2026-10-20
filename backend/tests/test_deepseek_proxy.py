import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fcntl", reason="The evaluation budget uses Linux advisory locks")

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from deepseek_proxy_entry import RESERVATION, Budget, BudgetExceeded, guarded_clients


def response():
    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10),
        model="offline-synthetic",
        system_fingerprint=None,
        choices=[SimpleNamespace(finish_reason="stop")],
    )


def test_budget_persists_reservation_before_call_then_refunds_and_stops(tmp_path):
    path = tmp_path / "budget.json"
    budget = Budget(path, "1", max_requests=1)
    lease = budget.begin()
    assert Decimal(json.loads(path.read_text())["spent_upper_bound_usd"]) == RESERVATION
    budget.finish(lease, response())
    state = json.loads(path.read_text())
    assert Decimal(state["spent_upper_bound_usd"]) == Decimal("0.000042")
    with pytest.raises(BudgetExceeded):
        budget.begin()
    assert len(json.loads(path.read_text())["calls"]) == 1


def test_unknown_call_keeps_full_reservation_and_ledger_cannot_be_reset(tmp_path):
    path = tmp_path / "budget.json"
    budget = Budget(path, ".5")
    lease = budget.begin()
    budget.finish(lease, error="OfflineTimeout")
    assert Decimal(json.loads(path.read_text())["spent_upper_bound_usd"]) == RESERVATION
    with pytest.raises(BudgetExceeded):
        budget.begin()
    with pytest.raises(ValueError, match="profile changed"):
        Budget(path, "2").begin()


def test_async_cancellation_releases_lease_without_charging_waiting_requests(tmp_path):
    openai = pytest.importorskip("openai")
    import httpx

    budget = Budget(tmp_path / "budget.json", "2")

    async def run():
        started = asyncio.Event()

        async def wait(request):
            started.set()
            await asyncio.Event().wait()

        with guarded_clients(budget):
            async with openai.AsyncOpenAI(
                api_key="offline-not-real",
                base_url="https://api.deepseek.com",
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(wait)),
            ) as client:
                kwargs = {
                    "model": "deepseek-flash",
                    "messages": [{"role": "user", "content": "offline"}],
                }
                first = asyncio.create_task(client.chat.completions.create(**kwargs))
                await asyncio.wait_for(started.wait(), timeout=1)
                second = asyncio.create_task(client.chat.completions.create(**kwargs))
                await asyncio.sleep(0.02)
                second.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await second
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
        assert len(json.loads(budget.path.read_text())["calls"]) == 1
        lease = budget.begin(blocking=False)
        budget.finish(lease, error="OfflineLeaseReleaseCheck")

    asyncio.run(run())


def test_sdk_guards_cover_sync_async_images_limits_and_no_retry(tmp_path):
    openai = pytest.importorskip("openai")
    import httpx

    calls = []

    def intercept(request):
        body = json.loads(request.content)
        assert request.url.host == "api.deepseek.com"
        assert body["model"] == "deepseek-flash"
        assert body["max_tokens"] == 8192 and body["thinking"] == {"type": "disabled"}
        assert body["messages"][0]["content"][1]["type"] == "image_url"
        calls.append(body)
        return httpx.Response(
            200,
            json={
                "id": "offline-only",
                "object": "chat.completion",
                "created": 0,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "OFFLINE_TRANSPORT_ONLY"},
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
            },
        )

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Offline transport only, no quality score."},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,AAAA", "detail": "low"},
                },
            ],
        }
    ]
    budget = Budget(tmp_path / "budget.json", "2")
    with guarded_clients(budget):
        with openai.OpenAI(
            api_key="offline-not-real",
            base_url="https://api.deepseek.com",
            http_client=httpx.Client(transport=httpx.MockTransport(intercept)),
        ) as client:
            assert client.max_retries == 0
            assert (
                client.chat.completions.create(model="deepseek-flash", messages=messages)
                .choices[0]
                .message.content
                == "OFFLINE_TRANSPORT_ONLY"
            )

        async def concurrent():
            async def respond(request):
                await asyncio.sleep(0.01)
                return intercept(request)

            async with openai.AsyncOpenAI(
                api_key="offline-not-real",
                base_url="https://api.deepseek.com",
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
            ) as client:
                await asyncio.wait_for(
                    asyncio.gather(
                        *[
                            client.chat.completions.create(
                                model="deepseek-flash", messages=messages
                            )
                            for _ in range(2)
                        ]
                    ),
                    timeout=2,
                )

        asyncio.run(concurrent())
        attempts = []

        def timeout(request):
            attempts.append(1)
            raise httpx.ConnectTimeout("offline mock")

        with openai.OpenAI(
            api_key="offline-not-real",
            base_url="https://api.deepseek.com",
            http_client=httpx.Client(transport=httpx.MockTransport(timeout)),
        ) as client:
            with pytest.raises(openai.APITimeoutError):
                client.chat.completions.create(model="deepseek-flash", messages=messages)
        assert len(attempts) == 1
    assert len(calls) == 3
    state = json.loads(budget.path.read_text())
    assert len(state["calls"]) == 4
    assert Decimal(state["spent_upper_bound_usd"]) == 3 * Decimal(".000042") + RESERVATION

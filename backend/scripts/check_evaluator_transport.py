"""Exercise the original VLM request path with an in-process HTTP mock.

The model response is explicitly synthetic and is never used as a quality score.
No real judge/API key is read or sent. Public tokenizer files may be cached.
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import tempfile
from io import BytesIO
from pathlib import Path

import httpx
from openai import OpenAI
from PIL import Image
from preflight_evaluation import http_proxy_environment

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reference/M2RAG"))


def check_transport(proxy=False):
    os.environ.update(http_proxy_environment(os.environ))
    from src.model import build_model

    model_name = "deepseek-flash" if proxy else "gpt-4o-2024-08-06"
    endpoint_host = "api.deepseek.com" if proxy else "offline.invalid"

    record = json.loads((ROOT / "runs/reference-multi-pilot-v1/14v6kn.json").read_text())
    image = record["result"]["output_images"][0]
    evidence = {
        "scope": "offline_deepseek_proxy_transport_not_original_quality"
        if proxy
        else "offline_original_vlm_transport_contract_not_quality",
        "synthetic_response": True,
        "external_judge_requests": 0,
        "intercepted_local_requests": 0,
    }

    def respond(request):
        assert request.url.host == endpoint_host
        payload = json.loads(request.content)
        assert payload["model"] == model_name
        if proxy:
            assert payload["thinking"] == {"type": "disabled"} and payload["max_tokens"] == 8192
        content = payload["messages"][0]["content"]
        images = [part["image_url"] for part in content if part["type"] == "image_url"]
        assert len(images) == 1 and images[0]["detail"] == "low"
        prefix, data = images[0]["url"].split(",", 1)
        assert prefix.lower().startswith("data:image/") and prefix.endswith(";base64")
        with Image.open(BytesIO(base64.b64decode(data))) as picture:
            picture.load()
            assert max(picture.size) <= 512
            evidence["transmitted_image_size"] = picture.size
        evidence["intercepted_local_requests"] += 1
        evidence["requested_model"] = payload["model"]
        return httpx.Response(
            200,
            json={
                "id": "offline-synthetic",
                "object": "chat.completion",
                "created": 0,
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "OFFLINE_TRANSPORT_CHECK_ONLY"},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    model = build_model(
        {
            "type": "OpenAIVLM",
            "params": {
                "model": model_name,
                "openai_api_key": "offline-placeholder-not-a-real-key",
                "openai_base_url": f"https://{endpoint_host}/v1",
                "use_local_image_file": True,
                "image_to_base64": True,
                "resize_image": [512, 512],
                "image_root": str(ROOT / "data/images"),
                "image_url": "http://0.0.0.0:65535/",
            },
        }
    )
    model.client.close()
    model.client = OpenAI(
        api_key="offline-placeholder-not-a-real-key",
        base_url=f"https://{endpoint_host}/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    result = model.chat(
        [
            {"type": "text", "text": "Offline transport check; do not evaluate quality."},
            {"type": "image_url", "image_url": {"url": image["cached_image_url"]}},
        ]
    )
    assert (
        result["response"] == "OFFLINE_TRANSPORT_CHECK_ONLY"
        and evidence["intercepted_local_requests"] == 1
    )
    original = ROOT / "data/images" / image["cached_image_url"].split(":65535/")[1]
    evidence["source_image_sha256"] = hashlib.sha256(original.read_bytes()).hexdigest()
    model.client.close()
    output = (
        ROOT
        / "runs/input-preflight"
        / ("deepseek-proxy-transport-contract.json" if proxy else "transport-contract.json")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--judge-protocol", choices=["original", "deepseek"], default="original")
    args = parser.parse_args()
    if args.judge_protocol == "deepseek":
        from deepseek_proxy_entry import Budget, guarded_clients

        with tempfile.TemporaryDirectory() as folder:
            with guarded_clients(Budget(Path(folder) / "synthetic-budget.json", "1")):
                check_transport(proxy=True)
    else:
        check_transport()


if __name__ == "__main__":
    main()

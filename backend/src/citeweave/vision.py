"""Visual caption verification with content- and model-keyed caching."""

import base64
import hashlib
import json
import os
from pathlib import Path

from . import config
from .generation import GPU_LOCK
from .web import cache_image

PROMPT = (
    "Describe what is visibly shown in this image in 2-3 precise sentences. "
    "Include readable chart labels when clear. Do not invent identity, dates or measurements."
)


def caption_images(images, generator, limit=10):
    import httpx

    directory = config.DATA / "cache/captions"
    directory.mkdir(parents=True, exist_ok=True)
    api = os.getenv("CITEWEAVE_VISION_BACKEND", "local") == "api"
    base = os.getenv(
        "CITEWEAVE_VISION_API_BASE",
        os.getenv("CITEWEAVE_API_BASE", "https://api.deepseek.com"),
    )
    model_name = os.getenv(
        "CITEWEAVE_VISION_API_MODEL", os.getenv("CITEWEAVE_API_MODEL", "deepseek-flash")
    )
    api_type = os.getenv("CITEWEAVE_API_TYPE", "deepseek")
    if api:
        revision = json.dumps(
            {"backend": "api", "base": base, "model": model_name, "type": api_type},
            sort_keys=True,
        )
    else:
        source = Path(config.VISION_MODEL) / "source.json"
        revision = source.read_text() if source.exists() else str(config.VISION_MODEL)
    caption_kind = "api_visual_description" if api else "local_visual_description"
    results, pending = [], []
    for image in images[:limit]:
        try:
            path = cache_image(image["url"])
            key = hashlib.sha256(
                path.read_bytes() + revision.encode() + PROMPT.encode()
            ).hexdigest()
            cached = directory / (key + ".json")
            item = {
                **image,
                "publisher_caption": image["caption"],
                "local_path": str(path),
            }
            if cached.exists():
                item.update(
                    caption=json.loads(cached.read_text())["caption"],
                    caption_kind=caption_kind,
                )
            else:
                pending.append((item, path, cached))
            results.append(item)
        except (ValueError, OSError, httpx.HTTPError) as e:
            results.append({**image, "image_error": str(e)[:150]})
    if not pending:
        return results + images[limit:]
    if api:
        key = (
            os.getenv("CITEWEAVE_VISION_API_KEY")
            or os.getenv("CITEWEAVE_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
        )
        if not key and api_type != "vllm":
            raise ValueError("Set CITEWEAVE_VISION_API_KEY or CITEWEAVE_API_KEY for vision API")
        with httpx.Client(timeout=180) as client:
            for item, path, cached in pending:
                # Reuse validated, resized JPEG bytes. Never delegate a remote
                # URL fetch (or its credentials) to the model server.
                uri = "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()
                response = client.post(
                    base.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {key}"} if key else {},
                    json={
                        "model": model_name,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "image_url", "image_url": {"url": uri}},
                                    {"type": "text", "text": PROMPT},
                                ],
                            }
                        ],
                        "max_tokens": 180,
                        "temperature": 0,
                        **(
                            {"chat_template_kwargs": {"enable_thinking": False}}
                            if api_type == "vllm"
                            else {"thinking": {"type": "disabled"}}
                        ),
                    },
                )
                response.raise_for_status()
                caption = response.json()["choices"][0]["message"]["content"]
                if not isinstance(caption, str) or not caption.strip():
                    raise ValueError("Vision API returned an empty description")
                item.update(caption=caption, caption_kind=caption_kind)
                cached.write_text(json.dumps({"caption": caption}, ensure_ascii=False))
        return results + images[limit:]
    import gc

    import torch
    from PIL import Image
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    with GPU_LOCK:
        generator.unload()
        processor = AutoProcessor.from_pretrained(config.VISION_MODEL, local_files_only=True)
        model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            config.VISION_MODEL,
            dtype=torch.bfloat16,
            device_map="cuda",
            local_files_only=True,
            attn_implementation="sdpa",
        ).eval()
        try:
            for item, path, cached in pending:
                with Image.open(path) as opened:
                    picture = opened.convert("RGB")
                prompt = processor.apply_chat_template(
                    [
                        {
                            "role": "user",
                            "content": [
                                {"type": "image"},
                                {"type": "text", "text": PROMPT},
                            ],
                        }
                    ],
                    tokenize=False,
                    add_generation_prompt=True,
                )
                batch = processor(text=[prompt], images=[picture], return_tensors="pt").to("cuda")
                with torch.inference_mode():
                    output = model.generate(**batch, max_new_tokens=180, do_sample=False)
                caption = processor.batch_decode(
                    output[:, batch.input_ids.shape[1] :], skip_special_tokens=True
                )[0]
                item.update(caption=caption, caption_kind="local_visual_description")
                cached.write_text(json.dumps({"caption": caption}, ensure_ascii=False))
                del batch, output
        finally:
            del model, processor
            gc.collect()
            torch.cuda.empty_cache()
    return results + images[limit:]

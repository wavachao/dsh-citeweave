"""One GPU-resident generator at a time; local runs require no API key."""

import gc
import os
import threading
import time

from . import config

GPU_LOCK = threading.RLock()


class Generator:
    name = "llm-citeweave-local"

    def __init__(self, adapter=None, max_new=None):
        self.adapter = adapter
        self.max_new = max_new or config.MAX_NEW
        self.model = None
        self.tokenizer = None
        self.calls = []
        self.last_response = None

    def load(self):
        if self.model is not None:
            return
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(config.MODEL, local_files_only=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            config.MODEL,
            dtype=torch.bfloat16,
            device_map="cuda",
            local_files_only=True,
            attn_implementation="sdpa",
        ).eval()
        if self.adapter:
            from peft import PeftModel

            self.model = PeftModel.from_pretrained(
                self.model,
                self.adapter,
                local_files_only=True,
                autocast_adapter_dtype=False,
            ).to(dtype=torch.bfloat16)

    def unload(self):
        self.model = None
        self.tokenizer = None
        gc.collect()
        import torch

        torch.cuda.empty_cache()

    def num_tokens_from_text(self, text):
        if self.tokenizer is None:
            from transformers import AutoTokenizer

            self.tokenizer = AutoTokenizer.from_pretrained(config.MODEL, local_files_only=True)
        return len(self.tokenizer.encode(text))

    @staticmethod
    def flatten(messages):
        return "".join(
            m["text"] if m["type"] == "text" else m["image_caption"]["caption"] for m in messages
        )

    def complete(self, prompt, system=None):
        self.last_response = None
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        started = time.monotonic()
        if os.getenv("CITEWEAVE_BACKEND", "local") == "api":
            import httpx

            key = os.getenv("CITEWEAVE_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
            vllm = os.getenv("CITEWEAVE_API_TYPE", "deepseek") == "vllm"
            if not key and not vllm:
                raise ValueError("Set CITEWEAVE_API_KEY or DEEPSEEK_API_KEY for the API backend")
            with httpx.Client(timeout=180) as client:
                r = client.post(
                    os.getenv("CITEWEAVE_API_BASE", "https://api.deepseek.com").rstrip("/")
                    + "/chat/completions",
                    headers={"Authorization": f"Bearer {key}"} if key else {},
                    json={
                        "model": os.getenv("CITEWEAVE_API_MODEL", "deepseek-flash"),
                        "messages": messages,
                        "max_tokens": self.max_new,
                        "temperature": 0,
                        **(
                            {
                                "chat_template_kwargs": {"enable_thinking": False},
                                "truncate_prompt_tokens": config.MAX_INPUT,
                            }
                            if vllm
                            else {"thinking": {"type": "disabled"}}
                        ),
                    },
                )
                r.raise_for_status()
                payload = r.json()
            text = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage", {})
            usage["input_truncated"] = False
            usage["output_budget_reached"] = payload["choices"][0].get("finish_reason") == "length"
        else:
            import torch

            with GPU_LOCK:
                self.load()
                ids = self.tokenizer.apply_chat_template(
                    messages,
                    tokenize=True,
                    add_generation_prompt=True,
                    return_tensors="pt",
                ).to("cuda")
                original_tokens = ids.shape[1]
                # Preserve instructions and question plus the end of retrieved context.
                # ponytail: fixed context budget; retrieval packing replaces truncation in production mode.
                if original_tokens > config.MAX_INPUT:
                    ids = torch.cat([ids[:, :2048], ids[:, -(config.MAX_INPUT - 2048) :]], dim=1)
                with torch.inference_mode():
                    out = self.model.generate(
                        ids,
                        attention_mask=torch.ones_like(ids),
                        do_sample=False,
                        max_new_tokens=self.max_new,
                        pad_token_id=self.tokenizer.eos_token_id,
                        use_cache=True,
                        logits_to_keep=1,
                    )
                text = self.tokenizer.decode(out[0, ids.shape[1] :], skip_special_tokens=True)
                usage = {
                    "prompt_tokens": ids.shape[1],
                    "completion_tokens": out.shape[1] - ids.shape[1],
                    "total_tokens": out.shape[1],
                    "original_prompt_tokens": original_tokens,
                    "input_truncated": original_tokens > config.MAX_INPUT,
                    "output_budget_reached": out.shape[1] - ids.shape[1] == self.max_new,
                }
        self.last_response = text
        self.calls.append({"seconds": time.monotonic() - started, **usage})
        return {"response": text, "usage": usage}

    def chat(self, messages):
        result = self.complete(self.flatten(messages))
        # Official multi-stage code sums exactly these three keys.
        result["usage"] = {
            k: result["usage"][k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        return result

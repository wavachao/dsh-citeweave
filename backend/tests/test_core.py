import json
import socket

import numpy as np
import pytest

from citeweave.data import split_key, training_groups
from citeweave.engine import Engine, align_images, parse_answer
from citeweave.train import ndcg
from citeweave.web import extract_page, public_url


def test_source_and_image_ids_cannot_be_invented():
    raw = json.dumps(
        {
            "title": "Test",
            "blocks": [
                {
                    "text": "Supported",
                    "source_ids": ["s0", "fake"],
                    "image_id": "evil",
                    "image_caption": "x",
                },
                {"text": "First", "source_ids": [], "image_id": "i0"},
                {"text": "Duplicate", "source_ids": [], "image_id": "i0"},
            ],
        }
    )
    out = parse_answer(raw, [{"id": "s0"}], [{"id": "i0"}])
    assert out["blocks"][0]["source_ids"] == ["s0"]
    assert [b["image_id"] for b in out["blocks"]] == [None, "i0", None]


def test_literal_model_newline_does_not_drop_image_evidence():
    raw = '{"title":"Test","blocks":[{"text":"First line\nSecond line","source_ids":["s0"],"image_id":"i0"}]}'
    out = parse_answer(raw, [{"id": "s0"}], [{"id": "i0"}])
    assert not out["parse_warning"]
    assert out["blocks"][0]["image_id"] == "i0"


def test_malformed_evidence_fields_do_not_crash():
    out = parse_answer('{"blocks":[{"text":"Answer","source_ids":{},"image_id":[]}]}', [], [])
    assert out["blocks"][0]["source_ids"] == []
    assert out["blocks"][0]["image_id"] is None


def test_markdown_fallback_places_only_matching_verified_images():
    answer = parse_answer(
        "# Shadows\n\n"
        + "A substantive explanation about shadows. " * 3
        + "\n\n"
        + "An unrelated paragraph. " * 5,
        [],
        [],
    )
    images = [
        {"id": "i0", "caption": "Shadow diagram"},
        {"id": "i1", "caption": "Unrelated decoration"},
    ]

    class Encoder:
        def encode(self, texts):
            assert len(texts) == 4
            return np.array([[1, 0, 0], [0, 1, 0], [1, 0, 0], [0, 0, 1]])

    align_images(answer, images, Encoder())
    assert answer["title"] == "Shadows"
    assert [b["image_id"] for b in answer["blocks"]] == ["i0", None]
    assert all(not b["source_ids"] for b in answer["blocks"])


def test_valid_json_can_intentionally_abstain_from_images():
    answer = parse_answer('{"blocks":[{"text":"No useful illustration."}]}', [], [])
    align_images(answer, [{"id": "i0", "caption": "Irrelevant"}], None)
    assert answer["blocks"][0]["image_id"] is None


def test_truncated_json_is_a_visible_failure_not_a_successful_answer():
    with pytest.raises(ValueError, match="did not finish"):
        parse_answer('{"title":"Test","blocks":[{"text":"unfinished', [], [])


def test_capped_generation_is_reported_as_incomplete():
    class Generator:
        def complete(self, prompt, system=None):
            return {"response": "Unfinished", "usage": {"output_budget_reached": True}}

    class Ranker:
        def select(self, query, images):
            return []

    with pytest.raises(ValueError, match="may be incomplete"):
        Engine(Generator(), Ranker()).answer("Why?", [], [])


def test_markdown_markers_cannot_invent_sources_images_or_captions():
    raw = "# Answer\n\nExplanation. [s0] [s99]\n\n[Image:i0]\n\nSecond [Image:i0] [Image:i9]"
    out = parse_answer(raw, [{"id": "s0"}], [{"id": "i0", "caption": "Actual source caption"}])
    assert out["blocks"][0]["source_ids"] == ["s0"]
    assert [b["image_id"] for b in out["blocks"]] == ["i0", None]
    assert out["blocks"][0]["image_caption"] == "Actual source caption"
    assert "i9" not in out["blocks"][1]["text"]


def test_plain_answer_preserves_comparison_formulas_and_source_identity():
    text = "For a < b and c > d, compare x<y with z>w."
    answer = parse_answer(text + " [s0]", [{"id": "s0"}], [])
    assert answer["blocks"][0]["text"] == text
    assert answer["blocks"][0]["source_ids"] == ["s0"]


def test_training_parser_excludes_instruction_example_and_groups_query(tmp_path):
    p = tmp_path / "train.jsonl"
    prompt = "![Example](images/99.jpeg)\n# Question\nWhy?\n\n# Webpages\n![Good](images/0.jpeg)\n![Bad](images/1.jpeg)"
    row = {"id": "a", "model_input": prompt, "model_response": "![Yes](images/0.jpeg)"}
    p.write_text(json.dumps(row) + "\n" + json.dumps({**row, "id": "b"}) + "\n")
    groups = list(training_groups(p))
    assert len(groups) == 1
    assert [c["label"] for c in groups[0]["candidates"]] == [1, 0]
    assert all(c["id"] != "images/99.jpeg" for c in groups[0]["candidates"])
    assert split_key(" Why? ") == split_key("why?")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1",
        "http://169.254.169.254",
        "http://[::1]",
        "http://localhost:8000",
        "https://user:pass@example.com",
    ],
)
def test_fetch_rejects_nonpublic_urls(url):
    with pytest.raises((ValueError, socket.gaierror)):
        public_url(url)


def test_page_preserves_image_source_and_figcaption():
    html = '<title>Guide</title><article><p>A useful explanation of the subject and its visible components.</p><figure><img src="/diagram.png" alt="Diagram"><figcaption>Actual source caption</figcaption></figure><img src="/logo.png"></article>'
    source, images = extract_page(html, "https://example.com/guide", "s0")
    assert source["title"] == "Guide"
    assert len(images) == 1
    assert images[0]["url"] == "https://example.com/diagram.png"
    assert images[0]["source_url"] == source["url"]
    assert images[0]["caption"] == "Actual source caption"


def test_optional_doh_avoids_polluted_dns_and_rejects_private_answers(monkeypatch):
    from citeweave import web

    address = ["208.80.154.224"]

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"Answer": [{"type": 1, "data": address[0]}]}

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, endpoint, params):
            assert endpoint == "https://dns.google/resolve"
            assert params["name"] == "en.wikipedia.org"
            return Response()

    monkeypatch.setenv("CITEWEAVE_DOH", "1")
    monkeypatch.setattr(web.httpx, "Client", Client)
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *a, **k: pytest.fail("System DNS used"))
    assert web._public_address("https://en.wikipedia.org/wiki/Eratosthenes") == address[0]
    address[0] = "127.0.0.1"
    with pytest.raises(ValueError, match="No public"):
        web._public_address("https://en.wikipedia.org/wiki/Eratosthenes")
    with pytest.raises(ValueError, match="Nonpublic"):
        web._public_address("http://127.0.0.1/")


def test_ndcg_accounts_for_order():
    assert ndcg([1, 0], [0.9, 0.1]) == 1
    assert 0 < ndcg([1, 0], [0.1, 0.9]) < 1

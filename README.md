# CiteWeave for DeepSeek Harness

Web search with sourced images for [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness).

[![CI](https://github.com/wavachao/dsh-citeweave/actions/workflows/ci.yml/badge.svg)](https://github.com/wavachao/dsh-citeweave/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-235c45)](LICENSE)

[简体中文](README.zh-CN.md) · [Backend](https://github.com/wavachao/dsh-citeweave/tree/main/backend) · [Reference](docs/reference.md) · [Releases](https://github.com/wavachao/dsh-citeweave/releases)

CiteWeave retrieves web evidence, evaluates candidate images, and supplies source links and illustrations to Harness. The configured DeepSeek model writes the answer, placing images beside the relevant explanation.

This repository contains the Harness plugin and its Python backend. The backend runs Qwen3.5-9B through vLLM, with CPU embeddings and reranking. Celery, Redis, and PostgreSQL handle retrieval jobs. On shared GPUs, the model starts on demand and releases memory after an idle period.

## Examples

**Geology** — Grand Canyon rock layers with a National Park Service diagram.

![Grand Canyon geology answer with a sourced diagram](docs/images/geography.png)

**Biology** — Monarch identification with a photograph of its wing markings.

![Monarch identification answer with a sourced photograph](docs/images/biology.png)

**Engineering** — A suspension bridge's load path, illustrated with the Golden Gate Bridge.

![Bridge engineering answer with a sourced photograph](docs/images/engineering.png)

[Image credits](docs/images/README.md)

## Installation

### Backend

Deploy the service from [backend/](https://github.com/wavachao/dsh-citeweave/tree/main/backend). The reference configuration uses Linux, Python 3.12, Docker, an RTX 3060 12 GB, and 32 GB RAM.

```sh
git clone https://github.com/wavachao/dsh-citeweave.git
cd dsh-citeweave/backend
```

Follow the [deployment guide](https://github.com/wavachao/dsh-citeweave/blob/main/backend/README.md) to install dependencies, download the models, and start the services.

### Harness plugin

In Harness Desktop or Web, open **Plugins → Add plugin** and enter:

```text
github:wavachao/dsh-citeweave#v0.5.0
```

Open **Installed plugins → CiteWeave → Configure CiteWeave**, enter the backend address and workspace access token, then save.

| Setting | Default | Description |
| --- | --- | --- |
| `endpoint` | `http://127.0.0.1:8765` | Backend address; also accepts `CITEWEAVE_ENDPOINT`. |
| `accessToken` | Empty | Workspace token; also accepts `CITEWEAVE_ACCESS_TOKEN`. |
| `timeoutMs` | `300000` | Tool timeout in milliseconds. |
| `maxImages` | `3` | Maximum images per search, from 1 to 8. |

The token field preserves the saved value when left blank. Command-line installation and environment configuration are covered in the [reference](docs/reference.md).

## Usage

> Explain how Eratosthenes measured Earth's circumference. Include a diagram and cite its source.

> Compare suspension bridges and cable-stayed bridges, with photographs showing their structural differences.

Harness calls `citeweave_search`, incorporates the evidence, and embeds images through its attachment store. The tool supports automatic search, up to five source URLs, image verification, and cache refresh. See the [tool reference](docs/reference.md#citeweave_search).

If the backend is unavailable, Harness continues answering without that tool result. Retrieval coverage and image availability depend on the source websites.

## Evaluation

See [benchmarks](https://github.com/wavachao/dsh-citeweave/tree/main/benchmarks) for comparison scripts, sample answers, and results.

## Project structure

| Path | Contents |
| --- | --- |
| [index.js](index.js), [client.js](client.js) | Harness tool and configuration interface |
| [backend/src/citeweave/](https://github.com/wavachao/dsh-citeweave/tree/main/backend/src/citeweave) | Retrieval API, worker, ranking, and model lifecycle |
| [backend/](https://github.com/wavachao/dsh-citeweave/tree/main/backend) | Python package, deployment configuration, and tests |
| [benchmarks/](https://github.com/wavachao/dsh-citeweave/tree/main/benchmarks) | Harness comparison and measurements |

The plugin targets Harness `0.2.1-rc.2` and Node.js 24+. Plugin and backend source share versioned releases; the installation archive contains the Harness plugin. Backend deployments use the matching repository tag.

## Contributing

See [CONTRIBUTING.md](https://github.com/wavachao/dsh-citeweave/blob/main/CONTRIBUTING.md) for development and tests. Report bugs through [GitHub Issues](https://github.com/wavachao/dsh-citeweave/issues), and vulnerabilities through [SECURITY.md](https://github.com/wavachao/dsh-citeweave/blob/main/SECURITY.md).

## License

[MIT](LICENSE). Based on [CiteWeave](https://github.com/wavachao/citeweave). Model and third-party resource licenses are listed in [backend/THIRD_PARTY.md](https://github.com/wavachao/dsh-citeweave/blob/main/backend/THIRD_PARTY.md); retrieved images retain their original licenses.

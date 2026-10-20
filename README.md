# CiteWeave for DeepSeek Harness

**Web evidence and sourced illustrations for DeepSeek Harness answers.**

[![CI](https://github.com/wavachao/dsh-citeweave/actions/workflows/ci.yml/badge.svg)](https://github.com/wavachao/dsh-citeweave/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-235c45)](LICENSE)
[![DeepSeek Harness](https://img.shields.io/badge/DeepSeek%20Harness-0.2.1--rc.2-5369f8)](https://github.com/deepseek-ai/deepseek-harness)

[简体中文](README.zh-CN.md) · [Backend setup](docs/backend.md) · [Reference](docs/reference.md) · [Releases](https://github.com/wavachao/dsh-citeweave/releases)

CiteWeave adds the `citeweave_search` tool to [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness). It retrieves webpage evidence, describes candidate images, and selects relevant illustrations. Harness writes the final answer with inline images and links to their original source pages.

- Search the web or retrieve up to five specified source pages.
- Select images using visual descriptions and relevance ranking.
- Store selected images in Harness's native attachment store and display them through its Markdown renderer.
- Preserve structured image references for session attachment export.
- Configure the backend in the shared Harness Desktop/Web plugin interface.
- Keep the GPU backend separate from the plugin; no Harness source changes are required.

## Requirements

| Component | Supported version / requirement |
| --- | --- |
| DeepSeek Harness | `0.2.1-rc.2` |
| Plugin host | Node.js 24 or later; Harness attachments and filesystem services |
| CiteWeave backend | The [pinned evidence API revision](docs/backend.md), reachable from the Harness host |
| Backend hardware | Linux, Python 3.12, and a CUDA-capable NVIDIA GPU; the complete pipeline has been exercised on a 24 GB RTX 4090 D |

Harness is under active development. This release declares compatibility with the exact version above. Installing the plugin does not install the Python backend or its model weights.

## Installation

### 1. Start CiteWeave

Follow [backend setup](docs/backend.md) to deploy the pinned revision with `POST /api/evidence`. An existing backend must expose this endpoint; CiteWeave's `main` branch does not currently provide it.

### 2. Install the plugin

Open **Plugins → Add plugin** in Harness Desktop or Web and enter this package locator:

```text
github:wavachao/dsh-citeweave#v0.1.1
```

Install it into the active profile. Harness Desktop and Web share the plugin management client and configuration interface. The package ships runnable ES modules and requires no build step or install scripts.

For command-line or archive installation, see [advanced installation](docs/reference.md#advanced-installation). Versioned archives and checksums are available on the [release page](https://github.com/wavachao/dsh-citeweave/releases/tag/v0.1.1). An npm publication is not required.

### 3. Connect Harness

Open **Plugins → Installed plugins → CiteWeave**, then open the component's **Configure CiteWeave** control and set:

- **Backend address** (`endpoint`): for example, `http://127.0.0.1:8765`.
- **Access token** (`accessToken`): the backend's workspace token, if authentication is enabled.
- **Timeout** (`timeoutMs`) and **Maximum images** (`maxImages`), if different from the defaults.

Save the settings. New tool calls use them immediately; environment variables and a host restart are not required. The token input is masked and does not reveal the saved value. Leave it blank to retain the saved token, or use **Clear saved token** to remove it. If `CITEWEAVE_ACCESS_TOKEN` is set on the host, it remains the fallback after clearing.

The configuration page connects to an existing backend; it does not start the GPU service or download its models. For a remote backend, use HTTPS or an SSH tunnel. The Harness host downloads the images; the browser does not need the backend credential.

## Usage

Ask a question that benefits from pictures:

> Explain how Eratosthenes measured Earth's circumference. Include a relevant diagram and cite its source.

> Compare suspension bridges and cable-stayed bridges, with photographs showing the structural differences.

The tool's description and prompt guidance help Harness choose it for illustrated answers. Tool selection and the final wording depend on the active answer model. CiteWeave returns evidence and images rather than generating a second answer.

The tool accepts a search query, optional source URLs, image verification, and cache refresh. See the [tool reference](docs/reference.md#citeweave_search).

## Configuration

| Setting | Default | Description |
| --- | --- | --- |
| `endpoint` | `CITEWEAVE_ENDPOINT` or `http://127.0.0.1:8765` | Backend service origin. |
| `accessToken` | `CITEWEAVE_ACCESS_TOKEN` or empty | Backend workspace token, sent as a Bearer credential. |
| `timeoutMs` | `180000` | Total tool timeout in milliseconds. |
| `maxImages` | `3` | Maximum images per search; range 1–8. |

Non-empty plugin settings take precedence over environment variables. [Environment variables and configuration patches](docs/reference.md#advanced-configuration) remain available for managed deployments.

## Operation and limitations

- The backend needs outbound access to public webpages and its configured search provider. Page availability, image quality, and retrieval coverage vary.
- When no suitable image is found, the tool returns text evidence without pictures. Individual image download failures are reported with the remaining evidence.
- Images are copied into Harness storage and included as native attachment references in tool results. Final-answer Markdown uses paths resolved by the active Harness filesystem. A filesystem provider must expose these files to the renderer; importing a session on another host may require path adaptation.
- The backend serializes GPU work. A busy worker returns `409`; wait for the active request before retrying. First-use model loading may require a longer timeout.
- Queries and supplied URLs are sent to the configured backend. Its search provider and source websites receive the corresponding retrieval requests. See [security and data handling](SECURITY.md).
- Source attribution does not grant permission to reuse an image. Retrieved material retains its original license.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for local installation, tests, packaging, and integration checks. Report reproducible bugs through [GitHub Issues](https://github.com/wavachao/dsh-citeweave/issues); report vulnerabilities privately using [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE). This is an independent integration for DeepSeek Harness, powered by [CiteWeave](https://github.com/wavachao/citeweave). DeepSeek Harness, backend models, and retrieved content retain their respective licenses.

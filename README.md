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

Use an initialized and configured Harness Web profile. For a first-time setup, run `dsh web` once and configure the answer model before installing the plugin. The examples below use the `web` profile; substitute your actual profile name if different.

Install the tagged source:

```sh
dsh plugin --profile web add github:wavachao/dsh-citeweave#v0.1.0
```

The package ships runnable ES modules. It requires no build step or install scripts.

Alternatively, download the release archive and install it locally:

```sh
curl -fL -o dsh-citeweave-0.1.0.tgz \
  https://github.com/wavachao/dsh-citeweave/releases/download/v0.1.0/dsh-citeweave-0.1.0.tgz
dsh plugin --profile web add ./dsh-citeweave-0.1.0.tgz
```

Release archives and their checksums are available on the [release page](https://github.com/wavachao/dsh-citeweave/releases/tag/v0.1.0). The package is distributed through GitHub; the installation command does not depend on an npm publication.

### 3. Connect Harness

Set the connection settings in the environment that starts Harness:

```sh
export CITEWEAVE_ENDPOINT=http://127.0.0.1:8765
# For a protected backend, also set CITEWEAVE_ACCESS_TOKEN to its workspace token.
dsh --profile web
```

In PowerShell:

```powershell
$env:CITEWEAVE_ENDPOINT = 'http://127.0.0.1:8765'
# $env:CITEWEAVE_ACCESS_TOKEN = 'your-workspace-token'
dsh --profile web
```

For a remote backend, use HTTPS or an SSH tunnel. The Harness host downloads the images; the browser does not need the backend address or credential. See [configuration and connection details](docs/reference.md#configuration).

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

Non-empty plugin settings take precedence over environment variables. Settings can also be managed through Harness's plugin configuration or a [patch file](docs/reference.md#configuration).

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

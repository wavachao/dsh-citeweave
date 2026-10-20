# Contributing

Issues and pull requests are welcome for both the Harness plugin and Python backend.

## Plugin development

Use Node.js 24+ and Harness `0.2.1-rc.2`.

```sh
git clone https://github.com/wavachao/dsh-citeweave.git
cd dsh-citeweave
npm ci
npm run check
npm test
npm run pack:release
```

`index.js` implements the tool, `client.js` provides the configuration interface, and `cordis.patch.yml` registers the plugin. The package uses runnable ES modules.

For manual integration testing, install the checkout in a configured test profile:

```sh
dsh plugin --profile citeweave-dev add .
```

Use a Web or Desktop profile with an answer model and reachable backend. Verify source links, inline images, session reopening, and attachment export.

## Backend development

The Python package and tests live in `backend/`. See its [README](backend/README.md) for environment setup and test commands. Unit tests run without GPU models; retrieval and lifecycle changes also need a live integration check.

Keep model weights, runtime data, credentials, and private session logs outside Git.

## Evaluation

The [Harness comparison](benchmarks/README.md) contains its prompts, runner, environment, and measurements. When changing retrieval or model behavior, record the tested revisions and include the answers needed to review the results.

## Releases

Plugin and backend source are released together using `v<package-version>` tags. CI checks the JavaScript plugin, Python backend, and installation archive. GitHub Releases provide the plugin archive, backend wheel and source distribution, and SHA-256 checksums. Backend deployments use the matching source tag.

Update the changelog for user-facing changes and keep English and Chinese installation instructions aligned.

Contributions are licensed under [MIT](LICENSE).

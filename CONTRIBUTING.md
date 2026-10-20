# Contributing

Issues and pull requests are welcome. Keep changes focused on the DeepSeek Harness integration; backend retrieval and model changes belong in [CiteWeave](https://github.com/wavachao/citeweave).

## Local development

Use Node.js 24 or later and DeepSeek Harness `0.2.1-rc.2`.

```sh
git clone https://github.com/wavachao/dsh-citeweave.git
cd dsh-citeweave
npm ci
npm run check
npm test
npm pack --dry-run
```

The entry point is a runnable ES module. No transpiler or build step is required. `cordis.patch.yml` registers the Host plugin, `index.js` implements the tool, and package resources provide its display metadata.

Install the checkout into a configured test profile for manual testing:

```sh
dsh plugin --profile citeweave-dev add .
dsh --profile citeweave-dev --dump-config
```

The example profile name is `citeweave-dev`; use the name of your test profile. A profile created only by `dsh plugin add` is base-backed. For image rendering checks, use a configured Web profile rather than assuming its name selects a Web surface. Start it with a reachable [backend](docs/backend.md) and a configured answer model. Ask an ordinary question requesting an illustration. Confirm that the model calls `citeweave_search`, embeds a selected image, and cites the original source page.

## Validation

Run `npm run check`, `npm test`, and `npm pack --dry-run` before submitting a change. Tests use deterministic local evidence and do not need GPU models, external search, or API credentials. Clean-profile installation requires package-registry access and pnpm. The suite packs the archive, installs it through the real Harness CLI, executes the installed tool with native Harness services, reopens stored images, and verifies their inclusion in the official ZIP export. These checks do not substitute for a live backend check.

For changes to tool guidance, API requests, image rendering, or attachments, also verify the relevant real integration path:

- Install the packed archive into a fresh Harness profile.
- Use the pinned CiteWeave backend and ask a natural-language question with suitable public sources.
- Check source links, inline image loading, and session reopening.
- Export the session and confirm that returned native image attachments are included.

Report which checks passed and which require an environment you did not have. Do not commit credentials, model weights, generated archives, or private conversation logs.

## Pull requests and releases

Explain the user-visible problem, the resulting behavior, and the checks performed. Update English and Chinese READMEs when changing installation, supported versions, or user-facing behavior. Update the reference for configuration and tool-contract changes.

Releases use `v<package-version>` tags and GitHub Release archives. A release must pass CI, contain the declared bundle entry points and display resources, and retain the supported Harness version declaration. Runtime compatibility changes require installation and integration checks against the new target version.

By contributing, you agree that your contribution is licensed under the project's [MIT license](LICENSE).

# Security policy

## Reporting a vulnerability

Report security vulnerabilities through [GitHub private vulnerability reporting](https://github.com/wavachao/dsh-citeweave/security/advisories/new). Include affected versions, reproduction steps, impact, and a minimal example. Do not include live access tokens, private queries, or sensitive session archives. Please avoid public issues for undisclosed vulnerabilities.

Security fixes target the latest release. This release supports DeepSeek Harness `0.2.1-rc.2`; other Harness versions have not been validated.

## Data and credentials

- The plugin sends queries and optional source URLs to the configured CiteWeave backend. The backend contacts its search provider and the requested public sources.
- Backend credentials are sent in the Authorization header for evidence and image requests. They are not placed in final-answer image links.
- Selected image bytes are copied into Harness's attachment store. Queries, source text, captions, and image references may be retained in Harness conversation history and session exports. Backend caching and retention are controlled by the separate CiteWeave deployment.
- Retrieved pages, captions, and images are untrusted source material. The plugin marks evidence as external data and restricts image-cache downloads to the configured backend origin. The configured backend itself is a trusted service.

Use HTTPS or an SSH tunnel for a remote backend. Supply tokens through the host environment or secret configuration, keep them out of version control, and redact them from issue reports. Deploy the backend according to its [pinned security and network guidance](https://github.com/wavachao/citeweave/blob/f6ac71eb6fe6335e52b9ee7a04f5a727c7fdbd24/docs/DEPLOYMENT.md).

Backend vulnerabilities should be reported to [CiteWeave](https://github.com/wavachao/citeweave/security); Harness vulnerabilities should be reported to [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness/security).

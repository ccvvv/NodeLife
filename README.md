# NodeLife

NodeLife is a cloud-based HTTPS availability recheck service for the **phone-tested final subscription** published by [AutoSubHub](https://github.com/ccvvv/AutoSubHub).

## Data source

- Repository: `ccvvv/AutoSubHub`
- Data branch: `published-subscriptions`
- Final subscription: `final/latest.yaml`
- Lifecycle metadata: `lifecycle.json`

NodeLife reads only the final subscription and its lifecycle metadata. It must never use `candidate/manifest.json` or candidate subscription files as its source of nodes.

## Intended automation

1. AutoSubHub publishes a new `final/latest.yaml` and updates `lifecycle.json`.
2. AutoSubHub sends a `repository_dispatch` event named `autohub-final-published` to trigger NodeLife promptly.
3. NodeLife fetches the latest upstream files after receiving the event; it does not trust node data in the event payload.
4. NodeLife merges upstream final nodes with the previous successful NodeLife output, deduplicates by the same stable fingerprint used by AutoSubHub, and performs HTTPS availability checks.
5. Only nodes passing the HTTPS check are kept in the next output. Failed nodes are not carried forward.
6. A six-hour scheduled check acts as a fallback. The scheduler checks the last successful build time so the interval rolls forward after each successful run.
7. Fetch, parse, encryption, or probe failures must preserve the previous successful output and state.

NodeLife does not repeat AutoSubHub's candidate filtering or phone download-speed tests.

## Probe policy

- Use Mihomo to route each HTTPS request through the individual node being tested.
- The test must not have a `DIRECT` fallback. A request that bypasses the node must never count as a pass.
- A node passes when at least one configured HTTPS target succeeds through its proxy.
- Probe concurrency, timeouts, targets, and Mihomo version are configured in `config/settings.yaml`.

## Fingerprint compatibility

For each proxy, remove the `name` field, serialize the remaining configuration as compact UTF-8 JSON with sorted keys, then calculate its SHA-256 digest. This matches AutoSubHub's final-subscription lifecycle fingerprint, so display-name changes do not create a new identity.

## Public-repository security

This repository is public. Do not commit plaintext proxy subscriptions, proxy credentials, access tokens, private keys, or complete subscription URLs.

- The generated subscription must be encrypted with age before it is committed as `data/latest.yaml.age`.
- The age recipient is a GitHub Actions Variable named `NODELIFE_AGE_RECIPIENT`.
- The age private identity is a GitHub Actions Secret named `NODELIFE_AGE_IDENTITY`.
- The AutoSubHub-to-NodeLife dispatch token is stored only as an Actions Secret in AutoSubHub, named `NODELIFE_DISPATCH_TOKEN`. NodeLife does not need a second copy.
- State and reports may contain hashes, timestamps, and aggregate counts only. They must not contain proxy credentials or raw node configurations.
- Temporary decrypted files belong under the runner's temporary directory and must be removed after use.
- Workflow logs must not print proxy names, addresses, UUIDs, passwords, or subscription contents.

## Configuration

Public, non-secret settings live in `config/settings.yaml`. Python dependencies are listed in `requirements.txt`. `.env.example` contains variable names only; never put real secrets in it.

## Project status

Initial configuration scaffold. The probe engine, encrypted output pipeline, event dispatch, and scheduled workflow still need implementation and end-to-end testing. Automation must not be considered production-ready until those tests pass.

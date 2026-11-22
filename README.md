# NodeLife

NodeLife is a cloud-based HTTPS availability recheck service for the **phone-tested final subscription** published by [AutoSubHub](https://github.com/ccvvv/AutoSubHub).

## Data source

- Repository: `ccvvv/AutoSubHub`
- Data branch: `published-subscriptions`
- Final subscription: `final/latest.yaml`
- NodeLife output: `data/latest.yaml`

NodeLife reads only AutoSubHub's final subscription. It must never use candidate manifests or candidate subscription files as its source of nodes.

## Automation

1. AutoSubHub publishes a new final subscription.
2. NodeLife fetches that upstream subscription and merges it with its previous successful output, deduplicating by stable proxy fingerprint.
3. NodeLife tests each node independently through Mihomo. Requests must use the tested proxy and must not have a DIRECT fallback.
4. Only nodes passing at least one configured HTTPS target are written to `data/latest.yaml`.
5. A scheduled run checks again every six hours. The workflow can also be started manually or runs when its own publishing code/configuration changes.
6. If fetching, parsing, or probing fails—or no nodes pass—the previous successful subscription is left untouched.

NodeLife does not repeat AutoSubHub's candidate filtering or phone download-speed tests.

## Probe policy

- Use Mihomo to route each HTTPS request through the individual node being tested.
- The test must not have a `DIRECT` fallback. A request that bypasses the node must never count as a pass.
- A node passes when at least one configured HTTPS target succeeds through its proxy.
- Probe concurrency, timeouts, targets, and Mihomo version are configured in `config/settings.yaml`.

## Fingerprint compatibility

For each proxy, remove the `name` field, serialize the remaining configuration as compact UTF-8 JSON with sorted keys, then calculate its SHA-256 digest. This matches AutoSubHub's final-subscription lifecycle fingerprint, so display-name changes do not create a new identity.

## Public subscription notice

This repository is public and the user has chosen **plaintext publication without age encryption**. The subscription at `data/latest.yaml` contains working proxy configurations and can be viewed, copied, and used by anyone. Do not put personal credentials, private account tokens, or unrelated secrets in the subscription.

## Subscription URL

`https://raw.githubusercontent.com/ccvvv/NodeLife/main/data/latest.yaml`

## Configuration

Public, non-secret settings live in `config/settings.yaml`. Python dependencies are listed in `requirements.txt`. Do not put real secrets in the repository.


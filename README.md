# NodeLife

NodeLife is a cloud-based HTTPS availability recheck service for the **phone-tested final subscription** published by [AutoSubHub](https://github.com/ccvvv/AutoSubHub).

## Cumulative release queue

NodeLife reads the Git history for `final/latest.yaml` on AutoSubHub's `published-subscriptions` branch instead of relying only on the moving latest URL.

- Every commit changing `final/latest.yaml` is a release batch.
- `data/queue_state.json` stores the newest collected commit and pending node configurations.
- If NodeLife misses several scheduled runs, it collects every release after the saved cursor, oldest first.
- Nodes are deduplicated across releases using the same stable SHA-256 fingerprint as AutoSubHub. Display-name-only changes do not create a second test.
- Nodes already in the successful output are not probed again just because they reappear in a later release.
- All new unique nodes are tested together in one run.
- Failed nodes remain in the durable pending queue and are retried on later runs.
- Existing successful output is retained if a batch has no passing nodes; an empty subscription is never published.
- If collection or probing fails before queue state is saved, the next run can safely collect the same releases again.

The pending queue contains proxy configurations. This repository already publishes its subscription as plaintext, so pending proxy details are also visible in this public repository. Do not add private credentials, account tokens, or unrelated secrets.

## Automation

1. AutoSubHub publishes a phone-tested final subscription revision.
2. NodeLife checks upstream final-file history every six hours, or on manual dispatch.
3. Missed revisions are accumulated and deduplicated into one pending queue.
4. NodeLife probes pending nodes independently through Mihomo, with no DIRECT fallback.
5. Passing nodes are added to `data/latest.yaml`; failed nodes remain queued for retry.
6. Queue state and subscription output are committed together.

NodeLife does not repeat AutoSubHub's candidate filtering or phone download-speed tests.

## Probe policy

- Use Mihomo to route each HTTPS request through the individual node being tested.
- No DIRECT fallback is permitted.
- A node passes when at least one configured HTTPS target succeeds through its proxy.
- Probe concurrency, timeouts, targets, and Mihomo version are configured in `config/settings.yaml`.

## Subscription URL

`https://raw.githubusercontent.com/ccvvv/NodeLife/main/data/latest.yaml`

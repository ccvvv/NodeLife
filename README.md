# NodeLife

NodeLife is a cloud-based HTTPS availability recheck service for the **phone-tested final subscription** published by [AutoSubHub](https://github.com/ccvvv/AutoSubHub).

## Input and recheck cycle

NodeLife downloads published subscription files over HTTPS from AutoSubHub's `published-subscriptions` branch. It does not clone AutoSubHub or use Git/API commit history to obtain candidates.

Each six-hour cycle:

1. Download `final/latest.yaml`, `final/previous.yaml`, and `final/older.yaml` as subscription inputs.
2. Merge those subscriptions with the previous NodeLife passing subscription.
3. Deduplicate nodes by stable SHA-256 configuration fingerprint; display-name-only changes do not create duplicates.
4. Re-test the entire merged pool through Mihomo. This is availability verification only; NodeLife does not repeat AutoSubHub's candidate filtering or phone download-speed tests.
5. Keep only nodes passing this cycle. Failed nodes are discarded and are not carried in a failure queue.
6. Generate both the Mihomo YAML subscription and the V2RayTun-compatible share-link subscription.
7. Use Git only at publication time to commit the refreshed output to this NodeLife repository.

If an upstream subscription cannot be fetched or parsed, the run fails closed and does not publish a partial result.

## Probe policy

- Each HTTPS request must pass through the individual node being tested.
- No DIRECT fallback is permitted.
- A node passes when at least one configured HTTPS target succeeds through its proxy.
- Probe concurrency, timeouts, targets, and Mihomo version are configured in `config/settings.yaml`.

## Published subscription links

Mihomo / Clash YAML:

`https://raw.githubusercontent.com/ccvvv/NodeLife/main/data/latest.yaml`

V2RayTun-compatible share-link subscription (Base64):

`https://raw.githubusercontent.com/ccvvv/NodeLife/main/data/v2raytun.txt`

Both outputs represent the same cycle's passing-node set. The V2RayTun output supports compatible SS, VMess, VLESS, Trojan, and Hysteria2 nodes; unsupported or incomplete Mihomo-only proxy types are skipped.

# NodeLife

NodeLife is a cloud-based availability recheck project for the final subscription published by [AutoSubHub](https://github.com/ccvvv/AutoSubHub).

## Planned workflow

- Check AutoSubHub's `published-subscriptions` branch and read `final/latest.yaml`.
- Read `candidate/manifest.json` and `lifecycle.json` to associate nodes with their first-observed timestamps.
- Compare the upstream final subscription fingerprint with the last successfully processed version.
- If the upstream final subscription has not changed, report that no recheck is needed.
- If it changed, merge it with the previous NodeLife result, deduplicate nodes by a stable configuration fingerprint, and recheck availability.
- Keep only nodes that pass the configured HTTPS availability gate in the next generated subscription.
- Run automatically every six hours and support manual dispatch.
- Preserve the previous successful output if fetching, parsing, or testing fails.

## Test policy

The planned cloud test uses the original proxy configuration and must verify that HTTPS requests actually pass through the node under test. At least one successful HTTPS target is sufficient; all configured targets failing means the node fails this round.

This project does not repeat AutoSubHub's candidate filtering or phone download-speed ranking.

## Lifecycle timestamps

AutoSubHub is being extended to publish `lifecycle.json` and a `lifecycle_id` in the candidate manifest. The lifecycle fingerprint excludes the display name, so renaming a node does not reset its first-observed timestamp.

Important: the first timestamp can only be established from the moment this metadata tracker is first deployed. It cannot reconstruct a node's true historical first-publication date from old data that never recorded that timestamp. NodeLife must preserve this distinction in lifecycle reports.

## Data and privacy

This repository is public. Never commit access tokens, source subscription URLs containing credentials, local secret files, or unreviewed node data.

Generated subscription files and detailed per-node records must not be published until the intended sharing permissions and output policy have been confirmed. Workflow logs must not print full proxy configurations, UUIDs, passwords, or complete subscription links.

## Upstream integration

- Repository: `ccvvv/AutoSubHub`
- Data branch: `published-subscriptions`
- Final subscription: `final/latest.yaml`
- Candidate metadata: `candidate/manifest.json`
- Lifecycle metadata: `lifecycle.json`

## Status

Initial project scaffold. The implementation and end-to-end workflow are not yet enabled.

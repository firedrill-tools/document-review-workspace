# Document review backend

Standalone synthetic document review API using LangChain, Claude and CopilotKit/AG-UI. Native model tools read documents and create source-bound edit proposals. A named local operator must separately approve before text changes; actor names are not authentication. This package has no production document connector or retired Firedrill API.

Python 3.12 and POSIX file locking are qualified. Dependencies are pinned in pyproject.toml and uv.lock. Provider/client ownership, strict completion/raw usage, cancellation/deadline guards and immutable review boundaries are described in the [repository compatibility record](https://github.com/firedrill-tools/document-review-workspace/blob/main/COMPATIBILITY.md).

## Offline cases

From this source directory, `uv sync --locked --extra test`. From an installed wheel, call the console command directly:

```sh
document-review-api --list-cases
document-review-api --init-case busy --workspace work/busy.json
document-review-api --show --workspace work/busy.json
document-review-api --without-agent --workspace work/busy.json --port 8124
```

All twelve case files are bundled. Initialization validates hashes, identity, strict relationships and populations, reserves a new private destination and refuses existing files/symlinks. Use another path to reset. Busy has twenty documents, one hundred sections and thirty prior human proposals: twelve approved, eight rejected and ten pending. Prior source/decision timestamps and actors are human imports, never model trials or usage. Legacy history is not relabeled automatically. Manifest focus stays out of model prompts.

GET `/documents` and `/documents/ID` show committed source/proposals. POST `/proposals/ID/decision` requires JSON `revision` (strict integer), `decision` (`approve` or `reject`) and `actor`. Approval rechecks the current section's exact original text, revision and protected flag. Stale proposals can be rejected. Other sections/documents and historical decisions remain intact.

## Native chat

Export `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` explicitly, then omit `--without-agent`. Optional `ANTHROPIC_BASE_URL` requires HTTPS or loopback HTTP; `REVIEW_WEB_ORIGIN` configures the local UI origin. No automatic dotenv loading. POST `/agent` is the actual AG-UI endpoint. The native API may incur charges; offline cases do not call a provider automatically.

The runtime owns one application-lifespan AsyncAnthropic/HTTPX2 client and async tools, with scoped tracing disabled and strict JSON completion before dispatch/final release. Provider SSE is disabled; AG-UI UI events stream normally. Chat history is client supplied; checkpoints live for one bounded run. Per-runtime overlapping runs and repeated thread/run IDs refuse a second execution. Model proposals require a source read in the same run. Exact already-pending proposals recover without another row. Source instruction text grants no extra tools or approval authority.

Private `.review-runs` receipts retain original provider evidence/unknown fields/usage separately from SDK messages and actual effects. GET `/runs/THREAD_ID/RUN_ID` inspects one receipt. A recording fault stops subsequent work, but already committed effects are retained and must be inspected. Missing measurements/cost remain unknown. Do not blindly retry uncertain publication. New state/receipt files are private; existing parent modes are preserved. Do not unlink the persistent `.lock` sidecar. Outside editors and Windows ownership are unqualified.

## Verification

```sh
uv run --locked python scripts/generate_data.py --check
uv run --locked --extra test pytest -q
uv build
```

The workspace's root distribution verifier checks fresh locked wheel/source installs, all bundled cases and installed console/module/API behavior outside the checkout. The separate Next.js frontend is available in the complete workspace source archive. Native tests use real SDK/HTTP with controlled responses, not live Claude judgment. Live provider quality/billing, the new Firedrill release/persisted cases, publication and licensing remain external gates.

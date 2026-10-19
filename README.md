# Document review workspace

A standalone synthetic [CopilotKit](https://docs.copilotkit.ai/) workspace with a Claude/LangChain agent. The agent reads documents and saves source-bound proposals for one section at a time. A named operator compares the original and proposed text, then approves or rejects. Only approval changes the committed document; the browser follows that state. This app has no production document connector.

## Start with an offline case

Qualified environment: Python 3.12, Node.js 24, `uv`, npm and POSIX file locking. No provider key is needed to list, initialize or inspect cases.

```sh
cd backend
uv sync --locked --extra test
uv run --locked document-review-api --list-cases
uv run --locked document-review-api --init-case busy --workspace ../work/busy.json
uv run --locked document-review-api --show --workspace ../work/busy.json
uv run --locked document-review-api --without-agent --workspace ../work/busy.json
```

The API binds `127.0.0.1:8124`. Offline mode supports document inspection and named operator decisions; it does not enable chat. Initialization validates hashes/identity/populations, creates a private new file and refuses existing files or symlinks. Reset at another path. Twelve cases/four profiles include starter, busy, ambiguous titles, protected/stale/rejected/already-proposed history, source instructions, noncontiguous IDs, Unicode, long source and revision limits. The busy desk has twenty documents, one hundred sections and thirty prior human proposals: twelve approved, eight rejected and ten pending. Prior human records have coherent source/revision, actors and UTC timestamps, with no invented provider trials/usage. See [scenarios](scenarios/README.md).

## Run native chat and the browser

For chat, export `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` for your enabled Claude account, then start the same API without `--without-agent`:

```sh
cd backend
uv run --locked document-review-api --workspace ../work/busy.json
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`. Next.js forwards CopilotKit chat to `/agent`; the frontend fetches committed state from the API. `.env.example` lists provider, workspace, origin and endpoint variables; export them explicitly. The API does not load dotenv files. `NEXT_PUBLIC_REVIEW_API_URL` is fixed at frontend build time; server-only `REVIEW_AGENT_URL` configures the AG-UI bridge. Chat sends selected synthetic document content to the provider and may incur charges. Listing or initializing cases never starts model calls.

Search the library by title or ID, select a document, then ask the copilot for a narrow edit. Existing pending/approved/rejected work remains visible. The displayed source when proposed is retained; stale/protected/revision-exhausted proposals cannot be approved. You can explicitly reject stale work without changing text. Copy a case's task from `--list-cases`; assessment focus and reference expectations never enter model context automatically.

## Review and state rules

- Model tools list, read and propose only. A proposal requires the target section read in the same run; exact original text/revision/protected flag are rechecked under publication. Source instructions grant no approval capability.
- The operator decision endpoint requires strict integer proposal revision, decision and a name. Approval rechecks the current section and changes only that section. Rejection preserves all committed text. Other sections/documents can change independently. Actor names are local labels, not authenticated identity or proof someone reviewed the text.
- Exact already-pending source/replacement/reason proposals recover without another row or new effect. A rejected proposal is historical work, not approval. Legacy history retains unknown provenance instead of invented dates or provider runs.
- Shared persistent POSIX advisory locks serialize cooperating Workspace instances/processes. New private temp files are flushed/fsynced then atomically replaced; never unlink the `.lock` sidecar. Outside editors do not participate in that ownership. Run one API process for its model client/run coordination; per-runtime overlapping chat is refused.
- New state/receipt files use mode 0600 and new private case directories 0700; existing parent modes are preserved. Keep state, receipts and `.env` out of Git. All examples are synthetic; there is no authentication. Windows ownership/signals remain unqualified.

## Native execution and observations

The normal path uses actual LangChain/Claude, CopilotKit and AG-UI with owned AsyncAnthropic/HTTPX2 clients. A version-guarded client accessor shim retains native ChatAnthropic logic without global clients or vendor cache/source edits. Clients belong to the API lifespan; checkpoints live for one run and client-supplied conversation history carries across turns. Provider JSON completion is checked before tools/final AG-UI success. Provider SSE is disabled; AG-UI UI events still stream.

Bounds: eight model calls/prepared HTTP, 24 tools, one tool per response, 4096 output tokens, no retries, phase/connect limits 30/five seconds and maximum overall 120 seconds. Scoped tracing is disabled. Request bytes are checked before dispatch; response evidence is capped at 1 MiB after buffering, not a memory/wire bound. True async tools and pre-replace active/deadline/cancellation checks prevent queued work publishing after a closed/expired run. A completed write cannot be undone by later cancellation.

Private `.review-runs` receipts retain input/instruction/state hashes, dataset identity, original provider bodies/unknown fields/IDs/usage/errors, separate SDK messages/tools and actual created proposal IDs bound to exact thread/run. `GET /runs/THREAD_ID/RUN_ID` inspects one receipt. Missing/partial/invalid/zero measurements remain distinct; cost stays unknown. A repeated thread/run ID refuses another execution. Recording/commit acknowledgement faults preserve actual state; inspect before a new run, never blindly retry an uncertain mutation. Final persistence failure may leave the last file running or an initial file empty, while exception evidence retains failure. Semantic editing quality still needs human source review.

## Verify

```sh
cd backend
uv run --locked python scripts/generate_data.py --check
uv run --locked --extra test pytest -q
uv build
cd ../frontend
npm ci
npm run typecheck
npx playwright install chromium
NEXT_PUBLIC_REVIEW_API_URL=http://127.0.0.1:38124 npm run build
npm run test:chat
cd ..
uv run --project backend --locked python scripts/check_distribution.py
```

The browser harness starts its own loopback API/production server; `uv` must be on PATH. Rebuild with the normal API URL afterward for local use. Eighty-eight backend checks and six production Chromium flows cover actual native HTTP, AG-UI, source-bound proposals, separate named approval/rejection, concurrent updates, cancellation/deadlines, recording faults, uncertain recovery, coherent versioned data, key-free CLI/API, busy/stale/noncontiguous UI and failure/recovery. Two flows exercise the full CopilotKit → AG-UI → native LangChain/Claude HTTP tool path; the other UI flows target state/navigation boundaries. Model Markdown HTML/unsafe URLs are verified inert, with trusted math and matching KaTeX CSS. Controlled SDK replies are not live Claude judgment.

The distribution verifier installs fresh locked backend wheel/sdist outside checkout, lists/privately initializes all twelve bundled cases and exercises installed console/module/API/state behavior. It builds `dist/document-review-workspace-0.2.0-source.tar.gz`, independently runs `npm ci`, typecheck and a production frontend build from that complete source archive. Generated runtime state/credentials are excluded. See [COMPATIBILITY.md](COMPATIBILITY.md), [backend package instructions](backend/README.md) and [PLAN.md](PLAN.md).

Live Claude quality/billing, the new released Firedrill integration and persisted cases, publication and licensing remain external gates. No retired or guessed Firedrill interface is included. Explore the [Firedrill example catalog](https://github.com/firedrill-tools/firedrill-example-catalog), [Firedrill](https://firedrill.run/) and [official developer documentation](https://docs.firedrill.run/).

## Current Firedrill integration

Released CLI/SDK 2.2.2, current command invocation, remote operator MCP and recovery are documented in the root firedrill/README.md. Offline checks preserve actual ASGI/AG-UI state/native key behavior and separate operator decisions. Authenticated persisted runs and live quality/cost remain parked separately.

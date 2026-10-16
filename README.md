# Document review workspace

A browser-facing [CopilotKit](https://docs.copilotkit.ai/) workspace with a Claude agent. The agent reads synthetic documents and saves proposed edits for one section at a time. A named operator reviews the current and proposed text, then approves or rejects. Only approval changes the committed document; the browser polls that committed state.

## Run locally

Requires Python 3.12+, Node.js 20+, `uv`, npm, and an Anthropic API key for chat. In one terminal:

```sh
cp fixtures/starter.json workspace.json
cd backend
uv sync --extra test
ANTHROPIC_API_KEY=... ANTHROPIC_MODEL=... uv run document-review-api
```

In a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`. The API binds `127.0.0.1:8124`; Next.js forwards CopilotKit chat to `/agent`. The frontend fetches document state directly from the API. Copy the fixture again to reset. Run one backend process for its in-memory agent conversations. State mutations across Workspace instances/processes serialize with a persistent POSIX advisory lock, bounded acquisition and unique private atomic temporary files; outside editors do not participate in that ownership. State schemas are bounded and reject invalid/duplicate identities and broken proposal relationships. There is no user authentication, so use only synthetic data on a local machine.

## Review rules and evidence

The agent can list documents, read one document and save an edit proposal. It cannot approve or apply edits. The decision endpoint checks the proposal revision, original section text and section revision before applying one replacement. Rejection leaves all text untouched. A protected section cannot receive a proposal. An unrelated section can change without invalidating a proposal for another section.

Run `cd backend && uv run --locked --extra test pytest -q` (57 checks), then `cd frontend && npm ci && npm run typecheck && npm run build`. The backend owns one native AsyncAnthropic/HTTPX2 client lifespan, bounds each run and validates original JSON completion before tools/final UI success. Model proposals must match a section read in that run. Exact existing pending proposals are recovery reads. Provider streaming is disabled; AG-UI UI events still stream. A version-guarded client accessor shim retains the actual ChatAnthropic/agent loop and avoids library-global clients. [COMPATIBILITY.md](COMPATIBILITY.md) records versions, bounds and evidence limits.

Private `.review-runs` receipts retain task/instruction/state hashes, original native HTTP/usage/errors, separate SDK messages/tools and actual created proposals. `GET /runs/THREAD_ID/RUN_ID` inspects one receipt. Missing measurements/cost are unknown; failed/uncertain publication never implies rollback. A repeated thread/run ID cannot execute again. Inspect state and its receipt before retrying with a new run. In-memory graph checkpoints live for one run; the browser supplies conversation history. This is a local synthetic app without authentication; actor names record a decision, not verified identity.

Three production Chromium flows exercise actual CopilotKit → AG-UI → native LangChain/Anthropic HTTP using controlled provider replies: proposal plus named approval, outage/unfinished response then recovery, and delayed selected-document reads/API reload recovery. They verify no text change before human approval and no script/javascript URL execution from model Markdown. To reproduce:

```sh
cd frontend
npx playwright install chromium
NEXT_PUBLIC_REVIEW_API_URL=http://127.0.0.1:38124 npm run build
npm run test:chat
```

The browser harness starts its own loopback API and production server; `uv` must be on PATH. It uses synthetic HTTP, no provider credits. For normal local operation, rebuild with the normal API URL from `.env.example`; Next.js fixes the public URL at build time. Chat waits for discovery and displays failures, and old document reads cannot replace a newer selection. These checks do not establish live Claude editing accuracy. Richer hash-bound cases, private initialization and installed-package follow-up remain in [PLAN.md](PLAN.md). The new released Firedrill interface, persisted scenarios, provider access/budget, publication and license remain parked external gates.

Explore related applications in the [Firedrill example catalog](https://github.com/firedrill-tools/firedrill-example-catalog). Product and setup references: [Firedrill](https://firedrill.run/) and the [official developer documentation](https://docs.firedrill.run/). Use documentation matching the qualified release; this repository records its current integration limits above.

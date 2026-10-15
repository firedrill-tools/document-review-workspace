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

Open `http://localhost:3000`. The API binds `127.0.0.1:8124`; Next.js forwards CopilotKit chat to `/agent`. The frontend fetches document state directly from the API. Copy the fixture again to reset. The local JSON store supports one backend process; its lock is process-local. There is no user authentication, so use only synthetic data on a local machine.

## Review rules and evidence

The agent can list documents, read one document and save an edit proposal. It cannot approve or apply edits. The decision endpoint checks the proposal revision, original section text and section revision before applying one replacement. Rejection leaves all text untouched. A protected section cannot receive a proposal. An unrelated section can change without invalidating a proposal for another section.

Run `cd backend && uv run pytest -q` and `cd frontend && npm run typecheck && npm run build`. Backend checks cover approval, rejection, stale competing edits, protected sections, unrelated sections and HTTP state. Frontend checks verify TypeScript and production compilation. A local browser check confirmed that approving a synthetic proposal updated the target section while the overview stayed intact, with no live model call. Live Claude chat and CopilotKit agent interaction remain pending provider access. Firedrill integration will be added only after the new released interface is qualified. No public license is selected.

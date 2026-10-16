# Document review requirement audit

## Reproduced gaps

- The real decision HTTP endpoint accepted revision=true as 1 and ignored undeclared fields, then approved and committed the edit. Strict extra-forbid decisions and direct store validation now reject booleans, floats, strings and unsafe revisions before mutation.
- Two independent Workspace instances reading the same JSON lost one proposal; one write failed FileNotFoundError because both used the same .tmp path. State changes now use a shared persistent POSIX advisory lock, unique private atomic temporary files and validation before replacement. Lock acquisition is bounded; busy callers reload before retrying. Concurrent instance/process checks preserve every independent proposal and untouched committed text.
- A real LangChain ChatAnthropic/AsyncAnthropic 1.14.0/httpx2 path dispatched propose_edit under max_tokens, saved a proposal, then failed on the second controlled 503 response. This gap is fixed in the owned JSON runtime: unfinished/inconsistent output is rejected before native tool dispatch and final UI success. Controlled HTTP is not live Claude judgment.

## Completed runtime follow-up

- Owned, version-guarded native ChatAnthropic/AsyncAnthropic/HTTPX2 lifespan, actual LangChain/CopilotKit/AG-UI graph, no provider streaming, scoped tracing disabled, strict original completion/arguments, bounded retries/requests/output/deadline and run-only checkpoints. Original usage/status/body/errors remain distinct from SDK defaults; missing values/cost stay unknown.
- True async tools, current-run exact source reads, under-lock rechecks and inside-publication active/deadline guards. Exact pending proposal recovery, durable thread/run receipts and actual failed/uncertain committed effects. Model tools cannot approve or apply text. Startup/cancel/deadline/shutdown closes owned work and clears checkpoints.
- 57 backend checks plus three production Chromium flows: native source/proposal and named human approval, visible provider/unfinished failure then recovery, and late selected-document reads/API reload recovery. Browser qualification exposed/fixed early discovery submission and invisible errors; source Markdown HTML/unsafe URLs are verified inert. Existing unrelated text/documents remain unchanged. See COMPATIBILITY.md.

## Current independent work

1. Add hash-bound starter/busy/ambiguous/boundary datasets with coherent prior human decisions and honest provenance, exclusive private initialization and scenario/task focus excluded from model prompts. Extend strict state validation without inventing old provider history.
2. Qualify fresh locked backend wheel/sdist and frontend archive outside checkout, including data and installed offline CLI/API, then exact-head CI/catalog evidence. Add targeted UI cases for busy/protected/stale/rejection behavior where the data adds a concrete risk.
3. Continue remaining Wave 2 projects after this standalone follow-up, keeping external gates parked.

## Parked external gates

Owner-supplied Claude key/model/budget and human semantic review; the new official Firedrill release and persisted positive/negative/recovery cases; publication and licensing. Keep this standalone synthetic app private and continue independent development.

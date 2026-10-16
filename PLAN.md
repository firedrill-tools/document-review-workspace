# Document review requirement audit

## Reproduced gaps

- The real decision HTTP endpoint accepted revision=true as 1 and ignored undeclared fields, then approved and committed the edit. Strict extra-forbid decisions and direct store validation now reject booleans, floats, strings and unsafe revisions before mutation.
- Two independent Workspace instances reading the same JSON lost one proposal; one write failed FileNotFoundError because both used the same .tmp path. State changes now use a shared persistent POSIX advisory lock, unique private atomic temporary files and validation before replacement. Lock acquisition is bounded; busy callers reload before retrying. Concurrent instance/process checks preserve every independent proposal and untouched committed text.
- A real LangChain ChatAnthropic/AsyncAnthropic 1.14.0/httpx2 path dispatched propose_edit under max_tokens, saved a proposal, then failed on the second controlled 503 response. This native completion gap remains the next implementation task. Controlled HTTP is not live Claude judgment.

## Current independent work

1. Finish strict bounded state/relationship, operator decision, atomic publication and concurrency qualification. Preserve source section revisions, unrelated document/section state and protected-section checks.
2. Require native JSON/SSE completion before tool dispatch and final release; preserve original usage/status/error/body evidence separately from normalized SDK events. Own/bound model clients, run/thread/checkpointer, cancellation, retries, tool writes and cleanup. Proposals require source read/current binding and exact recovery; no model approval capability.
3. Add hash-bound starter/busy/ambiguous/boundary cases with coherent prior human decisions and honest provenance. Exclusive private initialization, source-only task context and installed distributions.
4. Qualify actual production CopilotKit → AG-UI → native LangChain/Claude tool/proposal flow, visible failure/recovery and operator approval/rejection in Chromium. Address discovered UI failures, then verify locked backend wheel/sdist and frontend archive plus exact-head CI/catalog evidence.

## Parked external gates

Owner-supplied Claude key/model/budget and human semantic review; the new official Firedrill release and persisted positive/negative/recovery cases; publication and licensing. Keep this standalone synthetic app private and continue independent development.

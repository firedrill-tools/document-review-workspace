# Simulate this agent with Firedrill

Firedrill is a simulation platform for AI agents. Your coding agent can prepare
and operate these simulations; the application and its model run in your own
repository or CI.

Start in the repository root, not inside `firedrill/`:

```sh
npx firedrill-run init
```

Authorize Firedrill and select a project/environment. Installation choices are
optional; skip them when using the locked `firedrill/` toolchain below. This setup
does not invoke the target agent or grant it access to real business accounts.

The optional execution toolchain pins released CLI/SDK **2.2.2**, Node 22+ (October 19, 2026). The existing Anthropic/LangChain/CopilotKit runtime remains separately locked.

## Prepare and run

From the workspace root:

```sh
(cd backend && uv sync --locked --extra test)
npm ci --prefix firedrill --ignore-scripts --no-audit --no-fund
node firedrill/node_modules/@firedrill-run/cli/bin/firedrill.mjs validate firedrill/scenario.json --json --non-interactive
```

Validation is offline. Human authorization/scope selection uses `npx firedrill-run init`; automation uses protected `FIREDRILL_TOKEN`, `FIREDRILL_PROJECT_ID`, `FIREDRILL_ENVIRONMENT_ID`. The app independently needs `ANTHROPIC_API_KEY` and enabled `ANTHROPIC_MODEL` or recipe model parameter. With scope/provider budget authorized, use `node firedrill/simulate.mjs --preview` and then `node firedrill/simulate.mjs`.

The bounded sequential recipe initializes a private hash-bound document workspace and invokes its actual `create_app` factory, owned lifespan, ordinary `/agent` AG-UI handler and exact `/runs/{thread}/{run}` receipt. Starter/ambiguity cases use the default native runtime with no injected factory/model/client. Busy inspection calls the actual document GET endpoint without creating a model runtime. This is in-process ASGI qualification, not a browser/UI or hosted-network claim. Human proposal decisions and committed text are not target actions; existing protected sections, source/revision bindings and operator gates remain authoritative.

Before app work, `invocation.json` retains outer run/attempt/scenario IDs in private `.runs/firedrill/attempt-*`. Chat separately allocates unique application thread/run IDs, saves them before dispatch and saves original AG-UI response bytes. Success requires an exact correlated RUN_FINISHED, no RUN_ERROR, readable run receipt and confirmed runtime closure; HTTP 200 alone is insufficient. Inspection is explicitly model-free. Failures retain original output/run directory and nonzero exit, with actual proposal effects preserved; no rollback or remote billing guarantee is inferred. New attempts never reset earlier state or SDK recovery journals. Paths/AG-UI files are local evidence, not uploaded platform artifacts.

Only explicit reviewed case/document/message and optional model are accepted. Current ID-only invocation excludes controller/assessment data; unsupported Tool bindings are rejected and operator/CI credentials are removed from child dispatch. Only business context reaches model tools. The adapter grants no operator approval or publication authority.

## MCP and recovery

Configure remote OAuth operator MCP at **https://mcp.firedrill.run/mcp** using [host setup](https://docs.firedrill.run/guides/coding-agents). MCP prepares, queues and inspects; the local SDK/CLI executes the command target. Host OAuth and execution login are separate. Use `--run BATCH_ID` to attach queued work, `--resume OPERATION_ID` after uncertainty, and `--result BATCH_ID` to read retained results. Preserve SDK journals and local evidence. These scripts retain public SDK diagnostics and whole-batch exit status; a new simulation starts new work.

CI and the fresh locked source archive run offline integration tests with actual committed document inspection and native missing-key boundary. They establish wiring and cleanup, not live model quality, platform persistence, or uploaded captures. The observation recipe defines no grader/gate. Authenticated persisted happy/negative runs, paid model quality/cost, publication and licensing remain separate gates.

References: [SDK](https://docs.firedrill.run/sdk/typescript), [command targets](https://docs.firedrill.run/guides/callbacks), [operator MCP](https://docs.firedrill.run/guides/control-mcp), [CI](https://docs.firedrill.run/guides/ci).

## Offline verification

After installing the application dependencies and locked integration toolchain,
run `npm test --prefix firedrill` to exercise the adapter checks. These checks are
optional for first use and call no paid model. The Node 22+ requirement above is
for the Firedrill clients; it does not lower any application runtime requirement
in the root README.

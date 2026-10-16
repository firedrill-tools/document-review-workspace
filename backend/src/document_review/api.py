"""Local document review HTTP API with an owned native AG-UI runtime."""

import asyncio
from contextlib import aclosing, asynccontextmanager
import json
import os
from pathlib import Path

from ag_ui.core import EventType, RunErrorEvent
from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from copilotkit import LangGraphAGUIAgent
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .contracts import Decision
from .evidence import receipt_path
from .runtime import AgentRuntime
from .store import Conflict, Workspace


class RuntimeAgent(LangGraphAGUIAgent):
    def __init__(self, *, runtime, name, graph, description=None, config=None):
        self.runtime = runtime
        super().__init__(name=name, graph=graph, description=description, config=config)

    def clone(self):
        return type(self)(
            runtime=self.runtime,
            name=self.name,
            graph=self.graph,
            description=self.description,
            config={
                **{"recursion_limit": 64},
                **(dict(self.config) if self.config else {}),
            },
        )

    async def run(self, input):
        try:
            async with self.runtime.execution(
                input.model_dump(mode="json"),
                thread_id=input.thread_id,
                run_id=input.run_id,
            ) as run:
                async with aclosing(super().run(input)) as events:
                    async for event in events:
                        if event.type == EventType.RUN_ERROR:
                            failure = run.error or RuntimeError(event.message)
                            run.finish(error=failure)
                            yield RunErrorEvent(
                                type=EventType.RUN_ERROR,
                                message=str(failure) or type(failure).__name__,
                            )
                            return
                        if event.type == EventType.RUN_FINISHED:
                            self.runtime.complete(
                                run, {"event": event.model_dump(mode="json")}
                            )
                        yield event
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception as error:
            yield RunErrorEvent(
                type=EventType.RUN_ERROR, message=str(error) or type(error).__name__
            )


def create_app(
    workspace_path: Path, include_agent: bool = True, *, runtime_factory=None
) -> FastAPI:
    workspace = Workspace(workspace_path)

    @asynccontextmanager
    async def lifespan(app):
        if not include_agent:
            yield
            return
        factory = AgentRuntime if runtime_factory is None else runtime_factory
        async with factory(workspace) as runtime:
            app.state.runtime = runtime
            original = {id(route) for route in app.router.routes}
            try:
                add_langgraph_fastapi_endpoint(
                    app=app,
                    agent=RuntimeAgent(
                        runtime=runtime,
                        name="review_agent",
                        description="Document review copilot",
                        graph=runtime.graph,
                    ),
                    path="/agent",
                )
                app.openapi_schema = None
                yield
            finally:
                app.router.routes[:] = [
                    route for route in app.router.routes if id(route) in original
                ]
                app.openapi_schema = None

    app = FastAPI(title="Document review workspace", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.getenv("REVIEW_WEB_ORIGIN", "http://localhost:3000")],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/documents")
    def documents():
        return workspace.documents()

    @app.get("/documents/{document_id}")
    def document(document_id: str):
        try:
            return workspace.document(document_id)
        except KeyError:
            raise HTTPException(404, "unknown document")

    @app.post("/proposals/{proposal_id}/decision")
    def decide(proposal_id: str, body: Decision):
        try:
            return workspace.decide(
                proposal_id, body.revision, body.decision, body.actor
            )
        except KeyError:
            raise HTTPException(404, "unknown proposal")
        except Conflict as error:
            raise HTTPException(409, str(error))
        except ValueError as error:
            raise HTTPException(422, str(error))

    @app.get("/runs/{thread_id}/{run_id}")
    def receipt(thread_id: str, run_id: str):
        root = (
            app.state.runtime.output_root
            if include_agent and hasattr(app.state, "runtime")
            else workspace.path.parent / ".review-runs"
        )
        try:
            path = receipt_path(root, thread_id, run_id)
            with path.open("rb") as source:
                raw = source.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                raise ValueError("receipt exceeds inspection limit")
            return json.loads(raw)
        except FileNotFoundError:
            raise HTTPException(404, "unknown review run")
        except ValueError as error:
            raise HTTPException(422, str(error))

    return app


def main(argv=None):
    import argparse
    import sys
    from .datasets import initialize_case, list_cases

    parser = argparse.ArgumentParser(
        description="Synthetic document review API and private offline cases"
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--list-cases", action="store_true")
    action.add_argument("--init-case", metavar="CASE")
    action.add_argument("--show", action="store_true")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument(
        "--without-agent",
        action="store_true",
        help="model-free document inspection/operator decisions",
    )
    parser.add_argument("--port", type=int, default=8124)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1–65535")
    if args.init_case and args.workspace is None:
        parser.error("--init-case requires a fresh --workspace path")
    path = args.workspace or Path(
        os.getenv("DOCUMENT_WORKSPACE_FILE", "../workspace.json")
    )
    try:
        if args.list_cases:
            result = list_cases()
        elif args.init_case:
            result = initialize_case(args.init_case, args.workspace)
        elif args.show:
            result = Workspace(path).snapshot()
        else:
            import uvicorn

            uvicorn.run(
                create_app(path, include_agent=not args.without_agent),
                host="127.0.0.1",
                port=args.port,
            )
            return 0
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(
            json.dumps({"error": type(error).__name__, "message": str(error)}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

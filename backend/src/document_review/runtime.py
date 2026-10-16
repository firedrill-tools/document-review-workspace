"""One owned native client lifespan with isolated, bounded JSON review runs."""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import os
from pathlib import Path

from anthropic import AsyncAnthropic
from langgraph.checkpoint.memory import MemorySaver
from langsmith import tracing_context

from .agent import INSTRUCTIONS, build_agent
from .evidence import CURRENT, RunScope, publish, sha
from .native import OwnedChatAnthropic, aggregate_usage, create_http, endpoint
from .store import Conflict


class AgentRuntime:
    def __init__(
        self,
        workspace,
        *,
        transport=None,
        model=None,
        key=None,
        base_url=None,
        output_root=None,
        timeout=120,
        writer=publish,
    ):
        self.workspace, self.transport = workspace, transport
        self.model_name = model if model is not None else os.getenv("ANTHROPIC_MODEL")
        self.key = key if key is not None else os.getenv("ANTHROPIC_API_KEY")
        if not self.key or not self.key.strip():
            raise RuntimeError("ANTHROPIC_API_KEY is required for the review copilot")
        if (
            not isinstance(self.model_name, str)
            or not self.model_name.strip()
            or len(self.model_name) > 200
            or any(c.isspace() for c in self.model_name)
        ):
            raise ValueError("ANTHROPIC_MODEL must name an enabled Claude model")
        self.base_url = endpoint(
            base_url or os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        )
        self.output_root = (
            Path(output_root) if output_root else workspace.path.parent / ".review-runs"
        )
        self.timeout, self.writer = timeout, writer
        self.stack = AsyncExitStack()
        self.closed = False
        self.entered = False
        self.active_task = None
        self.checkpointer = None
        self.current_run = None

    async def __aenter__(self):
        if self.entered or self.closed:
            raise RuntimeError("review runtime cannot be entered twice")
        self.entered = True
        try:
            self.run_lock = asyncio.Lock()
            self.http = await self.stack.enter_async_context(
                create_http(self.transport)
            )
            self.client = await self.stack.enter_async_context(
                AsyncAnthropic(
                    api_key=self.key,
                    base_url=self.base_url,
                    max_retries=0,
                    timeout=30,
                    http_client=self.http,
                )
            )
            self.model = OwnedChatAnthropic(
                owned_async=self.client,
                model=self.model_name,
                api_key=self.key,
                base_url=self.base_url,
                max_retries=0,
                max_tokens=4096,
                timeout=30,
                disable_streaming=True,
                cache=False,
                model_kwargs={
                    "tool_choice": {"type": "auto", "disable_parallel_tool_use": True}
                },
            )
            self.checkpointer = self.stack.enter_context(MemorySaver())
            self.graph = build_agent(
                self.workspace, model=self.model, checkpointer=self.checkpointer
            )
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, kind, value, traceback):
        try:
            if (
                self.active_task is not None
                and self.active_task is not asyncio.current_task()
            ):
                self.active_task.cancel()
                await asyncio.gather(self.active_task, return_exceptions=True)
            if self.checkpointer is not None:
                threads = {
                    item.config["configurable"]["thread_id"]
                    for item in self.checkpointer.list(None)
                }
                for thread_id in threads:
                    await self.checkpointer.adelete_thread(thread_id)
        finally:
            try:
                await self.stack.__aexit__(kind, value, traceback)
            finally:
                self.closed = True

    @asynccontextmanager
    async def execution(self, state, *, thread_id, run_id):
        if self.closed or not self.entered:
            raise RuntimeError("review runtime is not active")
        if self.run_lock.locked():
            raise Conflict(
                "review runtime already has an active run; inspect it before retrying"
            )
        await self.run_lock.acquire()
        run = None
        token = None
        try:
            self.active_task = asyncio.current_task()
            run = RunScope(
                self.workspace,
                thread_id,
                run_id,
                state,
                self.model_name,
                self.output_root,
                timeout=self.timeout,
                writer=self.writer,
            )
            run.data["instructions_sha256"] = sha(INSTRUCTIONS.encode())
            run.save()
            self.current_run = run
            token = CURRENT.set(run)
            # Client supplies conversation history. Checkpoints only live for this run.
            await self.checkpointer.adelete_thread(thread_id)
            with tracing_context(enabled=False):
                async with asyncio.timeout(self.timeout):
                    yield run
                    if run.active:
                        raise RuntimeError(
                            "run ended without its completed final boundary"
                        )
        except BaseException as error:
            if run:
                try:
                    run.finish(error=error)
                except BaseException as recording:
                    run.data.update(
                        status="failed",
                        result=None,
                        evidence_error=f"{type(recording).__name__}: {recording}",
                    )
                error.evidence = run.data
                error.receipt_path = str(run.path)
            raise
        finally:
            try:
                if run:
                    await self.checkpointer.adelete_thread(thread_id)
            finally:
                if token is not None:
                    CURRENT.reset(token)
                self.current_run = None
                self.active_task = None
                self.run_lock.release()

    @staticmethod
    def complete(run, result):
        run.guard()
        if (
            run.last_accepted is None
            or run.last_accepted["body"].get("stop_reason") != "end_turn"
        ):
            raise RuntimeError("review run has no completed native final answer")
        run.finish(result=result)

    async def ainvoke(self, state, *, thread_id, run_id):
        async with self.execution(state, thread_id=thread_id, run_id=run_id) as run:
            result = await self.graph.ainvoke(
                state,
                config={
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": 64,
                },
            )
            message = result["messages"][-1]
            value = {
                "message": message.text,
                "receipt_path": str(run.path),
                "thread_id": thread_id,
                "run_id": run_id,
            }
            self.complete(run, value)
            return {
                **value,
                "reported_usage": aggregate_usage(run.data["provider_observations"]),
                "actual_effects": run.data["actual_effects"],
            }

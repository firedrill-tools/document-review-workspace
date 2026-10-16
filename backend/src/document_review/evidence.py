"""Private run receipts and active ownership of native model/tool work."""

import asyncio
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import time

from .contracts import identifier
from .store import Conflict

CURRENT = ContextVar("document_review_run", default=None)


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def receipt_path(root, thread_id, run_id):
    identifier(thread_id, "thread ID")
    identifier(run_id, "run ID")
    return Path(root).resolve() / (sha((thread_id + "\0" + run_id).encode()) + ".json")


def publish(path, value):
    staged = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf8",
            dir=path.parent,
            prefix=".run-",
            suffix=".tmp",
            delete=False,
        ) as file:
            staged = Path(file.name)
            json.dump(value, file, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(staged, path)
    finally:
        if staged:
            staged.unlink(missing_ok=True)


def scope():
    result = CURRENT.get()
    if result is None:
        raise RuntimeError("model tools require an owned active review run")
    result.guard()
    return result


class RunScope:
    def __init__(
        self,
        workspace,
        thread_id,
        run_id,
        state,
        model,
        root,
        *,
        timeout=120,
        writer=publish,
    ):
        identifier(thread_id, "thread ID")
        identifier(run_id, "run ID")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < timeout <= 120
        ):
            raise ValueError(
                "run timeout must be positive and no more than 120 seconds"
            )
        serialized = canonical(state)
        if len(serialized.encode()) > 100000:
            raise ValueError("chat input exceeds 100000 UTF-8 bytes")
        self.workspace, self.thread_id, self.run_id = workspace, thread_id, run_id
        self.deadline, self.active, self.error = time.monotonic() + timeout, True, None
        self.reads = {}
        self.tool_count = 0
        self.seen_tool_ids = set()
        self.last_accepted = None
        self.writer = writer
        self.path = receipt_path(root, thread_id, run_id)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        initial = workspace.snapshot()
        self.data = {
            "schema_version": 1,
            "thread_id": thread_id,
            "run_id": run_id,
            "requested_model": model,
            "versions": {
                name: version(name)
                for name in (
                    "langchain",
                    "langchain-anthropic",
                    "langchain-core",
                    "langgraph",
                    "langsmith",
                    "anthropic",
                    "httpx2",
                    "pydantic",
                    "copilotkit",
                    "ag-ui-langgraph",
                )
            },
            "status": "running",
            "started_at": now(),
            "finished_at": None,
            "input": state,
            "input_sha256": sha(serialized.encode()),
            "initial_state": initial,
            "final_state": None,
            "provider_observations": [],
            "sdk_observations": [],
            "tools": [],
            "actual_effects": None,
            "result": None,
            "error": None,
            "cost_usd": None,
        }
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            error = Conflict(
                "run ID already exists; inspect its original receipt and state before a new run"
            )
            error.receipt_path = str(self.path)
            raise error
        else:
            os.close(descriptor)
        try:
            self.save()
        except BaseException as error:
            self.active = False
            self.data.update(
                status="failed",
                result=None,
                evidence_error=f"{type(error).__name__}: {error}",
            )
            error.evidence = self.data
            error.receipt_path = str(self.path)
            raise

    def guard(self):
        if self.error is not None:
            raise self.error
        if not self.active:
            raise RuntimeError("review run is closed")
        if time.monotonic() >= self.deadline:
            raise TimeoutError("review run deadline expired")
        if asyncio.current_task().cancelling():
            raise asyncio.CancelledError()

    def save(self):
        from .native import aggregate_usage

        self.data["reported_usage"] = aggregate_usage(
            self.data["provider_observations"]
        )
        try:
            self.writer(self.path, self.data)
        except BaseException as error:
            self.error = error
            raise

    def tool(self, name, arguments, result=None, error=None):
        self.data["tools"].append(
            {
                "name": name,
                "arguments": deepcopy(arguments),
                "result": deepcopy(result),
                "error": {"name": type(error).__name__, "message": str(error)}
                if error
                else None,
                "at": now(),
            }
        )
        self.save()

    def start_tool(self):
        self.guard()
        self.tool_count += 1
        if self.tool_count > 24:
            raise ValueError("review tool invocation limit (24) reached")

    def finish(self, result=None, error=None):
        if not self.active:
            if error is not None:
                self.data.update(
                    status="failed",
                    result=None,
                    error={"name": type(error).__name__, "message": str(error)},
                )
                self.save()
            return
        error = error or self.error
        self.active = False
        for observation in self.data["provider_observations"]:
            if observation["status"] in {"prepared", "received"}:
                observation.update(
                    status="failed",
                    finished_at=now(),
                    error={
                        "name": type(error).__name__ if error else "IncompleteResponse",
                        "message": str(error)
                        if error
                        else "Native response did not finish",
                    },
                )
        self.data.update(
            status="failed" if error else "completed",
            finished_at=now(),
            result=result if error is None else None,
            error={"name": type(error).__name__, "message": str(error)}
            if error is not None
            else None,
        )
        try:
            final = self.workspace.snapshot()
            self.data["final_state"] = final
            before = {
                proposal["id"]
                for proposal in self.data["initial_state"]["state"]["proposals"]
            }
            created = [
                proposal["id"]
                for proposal in final["state"]["proposals"]
                if proposal["id"] not in before
                and proposal.get("created_by_run") == self.run_id
            ]
            self.data["actual_effects"] = {
                "created_proposal_ids": created,
                "applied_section_ids": [],
            }
        except BaseException as failure:
            self.data["snapshot_error"] = {
                "name": type(failure).__name__,
                "message": str(failure),
            }
            if error is None:
                self.data["status"] = "failed"
                self.data["result"] = None
                raise
        from .native import aggregate_usage

        self.data["reported_usage"] = aggregate_usage(
            self.data["provider_observations"]
        )
        self.save()

"""Pinned native ChatAnthropic ownership and JSON completion before SDK dispatch."""

from importlib.metadata import version
import json
from urllib.parse import urlsplit

from anthropic import AsyncAnthropic
import httpx2
from langchain_anthropic import ChatAnthropic
from pydantic import Field, PrivateAttr

from .contracts import StrictModel, identifier
from .evidence import now, scope, sha

LIMIT = 1048576
FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


class ListDocuments(StrictModel):
    pass


class ReadDocument(StrictModel):
    document_id: str = Field(min_length=1, max_length=100)


class ProposeEdit(ReadDocument):
    section_id: str = Field(min_length=1, max_length=100)
    replacement_text: str = Field(min_length=1, max_length=20000)
    reason: str = Field(min_length=1, max_length=2000)


ARGUMENTS = {
    "list_documents": ListDocuments,
    "read_document": ReadDocument,
    "propose_edit": ProposeEdit,
}


def endpoint(value):
    url = urlsplit(value)
    if (
        not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or not (
            url.scheme == "https"
            or url.scheme == "http"
            and url.hostname in {"127.0.0.1", "localhost", "::1"}
        )
    ):
        raise ValueError(
            "Anthropic endpoint requires HTTPS or loopback HTTP without credentials/query/fragment"
        )
    return value


def usage(body):
    raw = body.get("usage") if isinstance(body, dict) else None
    fields = {
        key: raw.get(key)
        if isinstance(raw, dict)
        and type(raw.get(key)) is int
        and 0 <= raw[key] <= 2**53 - 1
        else None
        for key in FIELDS
    }
    complete = all(value is not None for value in fields.values())
    total = sum(fields.values()) if complete else None
    if total is not None and total > 2**53 - 1:
        complete = False
        total = None
    return {
        "fields": fields,
        "complete": complete,
        "total_tokens": total,
        "cost_usd": None,
    }


def aggregate_usage(observations):
    values = [item.get("reported_usage") for item in observations]
    fields = {
        key: sum(value["fields"][key] for value in values)
        if values
        and all(value and value["fields"][key] is not None for value in values)
        else None
        for key in FIELDS
    }
    fields = {
        key: value if value is None or value <= 2**53 - 1 else None
        for key, value in fields.items()
    }
    complete = (
        bool(values)
        and all(value and value["complete"] for value in values)
        and all(value is not None for value in fields.values())
    )
    total = sum(value["total_tokens"] for value in values) if complete else None
    if total is not None and total > 2**53 - 1:
        complete = False
        total = None
    return {
        "prepared_attempts": len(observations),
        "fields": fields,
        "complete": complete,
        "total_tokens": total,
        "cost_usd": None,
    }


def validate_completion(body, run):
    if (
        not isinstance(body, dict)
        or body.get("type") != "message"
        or body.get("role") != "assistant"
    ):
        raise ValueError("native response is not an assistant message")
    identifier(body.get("id"), "native message ID")
    if not isinstance(body.get("model"), str) or not body["model"].strip():
        raise ValueError("native response model is absent")
    parts = body.get("content")
    if (
        not isinstance(parts, list)
        or not parts
        or any(
            not isinstance(part, dict) or part.get("type") not in {"text", "tool_use"}
            for part in parts
        )
    ):
        raise ValueError("native content is empty or unsupported")
    if any(
        part.get("type") == "text" and not isinstance(part.get("text"), str)
        for part in parts
    ):
        raise ValueError("native text content is malformed")
    calls = [part for part in parts if part["type"] == "tool_use"]
    finish = body.get("stop_reason")
    if body.get("stop_sequence") is not None:
        raise ValueError("unexpected native stop sequence")
    if finish == "tool_use" and len(calls) == 1:
        call = calls[0]
        identifier(call.get("id"), "tool call ID")
        if call["id"] in run.seen_tool_ids:
            raise ValueError("native tool call ID replayed")
        schema = ARGUMENTS.get(call.get("name"))
        if schema is None or not isinstance(call.get("input"), dict):
            raise ValueError("unsupported native review tool")
        schema.model_validate(call["input"])
        run.seen_tool_ids.add(call["id"])
    elif (
        finish == "end_turn"
        and not calls
        and any(part["type"] == "text" and part["text"].strip() for part in parts)
    ):
        pass
    else:
        raise ValueError(f"native response is unfinished or inconsistent ({finish!r})")
    return calls


def nonfinite(value):
    raise ValueError("nonfinite JSON constant")


async def request(request):
    run = scope()
    if request.method != "POST" or not request.url.path.endswith("/messages"):
        raise ValueError("only native Messages JSON is qualified")
    if len(run.data["provider_observations"]) >= 8:
        raise ValueError("review prepared HTTP limit (8) reached")
    raw = await request.aread()
    if len(raw) > LIMIT:
        raise ValueError("native request exceeds 1 MiB")
    body = json.loads(raw)
    if body.get("stream") is True:
        raise ValueError("native provider streaming is not qualified")
    if body.get("max_tokens") != 4096:
        raise ValueError("unexpected native output budget")
    if {tool.get("name") for tool in body.get("tools", [])} != set(ARGUMENTS):
        raise ValueError("only server-owned review tools may be exposed")
    run.data["provider_observations"].append(
        {
            "attempt": len(run.data["provider_observations"]) + 1,
            "status": "prepared",
            "started_at": now(),
            "finished_at": None,
            "path": request.url.path,
            "request_body": body,
            "input_sha256": sha(raw),
            "http_status": None,
            "request_id": None,
            "body": None,
            "body_sha256": None,
            "response_id": None,
            "response_model": None,
            "finish_reason": None,
            "reported_usage": None,
            "error": None,
        }
    )
    run.save()
    run.guard()


async def response(response):
    run = scope()
    observation = run.data["provider_observations"][-1]
    observation.update(
        status="received",
        http_status=response.status_code,
        request_id=response.headers.get("request-id"),
    )
    try:
        raw = await response.aread()
        truncated = len(raw) > LIMIT
        captured = raw[:LIMIT]
        try:
            body = json.loads(captured, parse_constant=nonfinite)
        except ValueError:
            body = captured.decode("utf8", errors="replace")
        observation.update(
            body=body,
            body_sha256=None if truncated else sha(raw),
            captured_sha256=sha(captured),
            truncated=truncated,
            reported_usage=usage(body),
        )
        if isinstance(body, dict):
            observation.update(
                response_id=body.get("id"),
                response_model=body.get("model"),
                finish_reason=body.get("stop_reason"),
            )
        run.save()
        run.guard()
        if truncated:
            raise ValueError("native response exceeds 1 MiB evidence limit")
        if response.is_success:
            validate_completion(body, run)
            observation["status"] = "accepted"
            run.last_accepted = observation
        else:
            observation["status"] = "http_error"
        run.save()
    except BaseException as error:
        run.error = run.error or error
        observation.update(
            status="failed", error={"name": type(error).__name__, "message": str(error)}
        )
        run.save()
        raise
    finally:
        observation["finished_at"] = now()
        await response.aclose()


class OwnedChatAnthropic(ChatAnthropic):
    """Version-guarded client accessor shim; native formatting/parsing/tool loop inherited.

    1.7.6 has no public client constructor field. Override only its cached
    accessors to avoid library-global HTTP clients; no vendor cache/source edits.
    """

    _owned_async: AsyncAnthropic = PrivateAttr()

    def __init__(self, *, owned_async, **options):
        if version("langchain-anthropic") != "1.7.6":
            raise RuntimeError("ChatAnthropic ownership shim needs requalification")
        super().__init__(**options)
        self._owned_async = owned_async

    @property
    def _async_client(self):
        return self._owned_async

    @property
    def _client(self):
        raise RuntimeError("review runtime owns async-only native model execution")


def create_http(transport=None):
    return httpx2.AsyncClient(
        transport=transport,
        timeout=httpx2.Timeout(30, connect=5),
        follow_redirects=False,
        event_hooks={"request": [request], "response": [response]},
    )

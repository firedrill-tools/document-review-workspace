"""Installed-style child CLI and model-free actual HTTP operator flow."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


def environment():
    env = {
        **os.environ,
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }
    for key in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_URL",
    ):
        env.pop(key, None)
    return env


def command(*args):
    return [sys.executable, "-m", "document_review.api", *args]


def run(tmp_path, *args):
    return subprocess.run(
        command(*args),
        cwd=tmp_path,
        env=environment(),
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_real_model_free_cli_lists_initializes_and_inspects_without_resetting_existing_state(
    tmp_path,
):
    listing = run(tmp_path, "--list-cases")
    assert listing.returncode == 0 and len(json.loads(listing.stdout)["cases"]) == 12
    path = tmp_path / "case" / "workspace.json"
    initialized = run(tmp_path, "--init-case", "busy", "--workspace", str(path))
    assert initialized.returncode == 0 and path.stat().st_mode & 0o777 == 0o600
    before = path.read_bytes()
    refused = run(tmp_path, "--init-case", "starter", "--workspace", str(path))
    assert (
        refused.returncode == 1
        and json.loads(refused.stderr)["error"] == "FileExistsError"
        and path.read_bytes() == before
    )
    shown = json.loads(run(tmp_path, "--show", "--workspace", str(path)).stdout)
    assert (
        shown["state"]["dataset"]["case_id"] == "busy"
        and len(shown["state"]["proposals"]) == 30
    )


def test_real_cli_requires_explicit_init_destination_and_refuses_unknown_cases(
    tmp_path,
):
    assert run(tmp_path, "--init-case", "starter").returncode == 2
    path = tmp_path / "unknown.json"
    result = run(tmp_path, "--init-case", "unknown-case", "--workspace", str(path))
    assert (
        result.returncode == 1
        and not path.exists()
        and "unknown" in json.loads(result.stderr)["message"]
    )


def test_real_without_agent_server_needs_no_key_and_commits_only_a_named_operator_decision(
    tmp_path,
):
    path = tmp_path / "workspace.json"
    assert (
        run(
            tmp_path, "--init-case", "already-proposed", "--workspace", str(path)
        ).returncode
        == 0
    )
    initial = json.loads(path.read_text())
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    child = subprocess.Popen(
        command("--without-agent", "--workspace", str(path), "--port", str(port)),
        cwd=tmp_path,
        env=environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                with urlopen(base + "/documents", timeout=1) as response:
                    documents = json.load(response)
                break
            except URLError:
                if child.poll() is not None or time.monotonic() >= deadline:
                    raise AssertionError("model-free API did not start")
                time.sleep(0.05)
        assert len(documents) == 2 and json.loads(path.read_text()) == initial
        proposal = initial["proposals"][0]
        request = Request(
            base + f"/proposals/{proposal['id']}/decision",
            method="POST",
            data=json.dumps(
                {
                    "revision": 1,
                    "decision": "approve",
                    "actor": "offline-human-reviewer",
                }
            ).encode(),
            headers={"content-type": "application/json"},
        )
        with urlopen(request, timeout=3) as response:
            result = json.load(response)
        assert result["proposal"]["status"] == "approved"
        current = json.loads(path.read_text())
        assert (
            current["documents"][0]["sections"][0]["text"]
            == proposal["replacement_text"]
        )
        assert (
            current["documents"][0]["sections"][1:]
            == initial["documents"][0]["sections"][1:]
        )
        assert current["documents"][1] == initial["documents"][1]
    finally:
        if child.poll() is None:
            child.terminate()
        try:
            child.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate()

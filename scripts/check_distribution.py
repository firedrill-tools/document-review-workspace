"""Fresh locked backend wheel/sdist and complete frontend source archive outside checkout."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import tomllib
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
VERSION = tomllib.loads((BACKEND / "pyproject.toml").read_text())["project"]["version"]
UV = os.environ.get("UV") or shutil.which("uv")
NPM = shutil.which("npm")
if not UV or not NPM:
    raise RuntimeError("uv and npm are required for distribution qualification")
ENV = {
    **os.environ,
    "NEXT_TELEMETRY_DISABLED": "1",
    "COPILOTKIT_TELEMETRY_DISABLED": "true",
    "SCARF_ANALYTICS": "false",
    "NO_PROXY": "127.0.0.1,localhost",
    "no_proxy": "127.0.0.1,localhost",
}
for key in (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_URL",
    "VIRTUAL_ENV",
    "PYTHONPATH",
    "PYTHONHOME",
):
    ENV.pop(key, None)


def run(command, cwd, check=True):
    result = subprocess.run(
        [str(part) for part in command],
        cwd=cwd,
        env=ENV,
        capture_output=True,
        text=True,
        timeout=240,
    )
    if check and result.returncode:
        raise RuntimeError(
            f"command failed: {command[0]} {command[1:3]}\n{result.stdout[-2000:]}\n{result.stderr[-3000:]}"
        )
    return result


def exercise(python, base):
    cli = [python, "-I", "-m", "document_review.api"]
    run([python.parent / "document-review-api", "--help"], base)
    manifest = json.loads(run([*cli, "--list-cases"], base).stdout)
    assert len(manifest["cases"]) == 12 and manifest["version"] == 1
    for case in manifest["cases"]:
        path = base / f"{case['id']}.json"
        result = json.loads(
            run([*cli, "--init-case", case["id"], "--workspace", path], base).stdout
        )
        assert (
            result["fixture_sha256"] == case["sha256"]
            and path.stat().st_mode & 0o777 == 0o600
        )
    existing = base / "busy.json"
    before = existing.read_bytes()
    assert (
        run(
            [*cli, "--init-case", "starter", "--workspace", existing], base, False
        ).returncode
        == 1
        and existing.read_bytes() == before
    )
    shown = json.loads(run([*cli, "--show", "--workspace", existing], base).stdout)
    assert (
        len(shown["state"]["documents"]) == 20
        and len(shown["state"]["proposals"]) == 30
    )
    program = """
import json,sys
from pathlib import Path
import document_review
from document_review.api import create_app
from document_review.store import Conflict,Workspace
assert Path(document_review.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
base=Path(sys.argv[1]);busy=Workspace(base/'busy.json').snapshot()['state']
assert sum(len(doc['sections']) for doc in busy['documents'])==100
assert all(item['origin']=='human_import' and item['created_by_run'] is None for item in busy['proposals'])
assert {status:sum(item['status']==status for item in busy['proposals']) for status in ('approved','rejected','pending')}=={'approved':12,'rejected':8,'pending':10}
store=Workspace(base/'already-proposed.json');before=store.document('doc-101')['document'];pending=store.document('doc-101')['proposals'][0]
assert store.propose('doc-101','overview',pending['replacement_text'],pending['reason'])['proposal_replayed'] is True
store.decide(pending['id'],1,'approve','installed-human-reviewer');after=store.document('doc-101')['document']
assert after['sections'][0]['text']==pending['replacement_text'] and after['sections'][1:]==before['sections'][1:]
app=create_app(base/'starter.json',include_agent=False);assert {route.path for route in app.routes}>={'/documents','/documents/{document_id}','/proposals/{proposal_id}/decision'}
stale=Workspace(base/'stale-competing-edit.json');current=stale.document('doc-101')['document']
try:stale.decide('human-0001',1,'approve','installed-human-reviewer')
except Conflict:pass
else:raise AssertionError('stale source applied')
stale.decide('human-0001',1,'reject','installed-human-reviewer');assert stale.document('doc-101')['document']==current
limit=Workspace(base/'revision-limit.json');proposal=limit.propose('doc-101','overview','Cannot apply another revision.','Installed boundary probe')
try:limit.decide(proposal['id'],1,'approve','installed-human-reviewer')
except Conflict:pass
else:raise AssertionError('unsafe revision committed')
"""
    run([python, "-I", "-c", program, base], base)


def source_archive():
    artifact = ROOT / "dist" / f"document-review-workspace-{VERSION}-source.tar.gz"
    artifact.parent.mkdir(exist_ok=True)
    entries = [
        "README.md",
        ".gitignore",
        ".github",
        "AGENTS.md",
        "PLAN.md",
        "COMPATIBILITY.md",
        ".env.example",
        "fixtures",
        "scripts",
        "backend/pyproject.toml",
        "backend/uv.lock",
        "backend/README.md",
        "backend/AGENTS.md",
        "backend/src",
        "backend/data",
        "backend/fixtures",
        "backend/scripts",
        "backend/tests",
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/next.config.ts",
        "frontend/next-env.d.ts",
        "frontend/tsconfig.json",
        "frontend/AGENTS.md",
        "frontend/app",
        "frontend/public",
        "frontend/e2e-chat",
        "frontend/playwright.chat.config.ts",
    ]
    excluded = {
        "node_modules",
        ".venv",
        ".next",
        ".e2e",
        ".review-runs",
        "__pycache__",
        ".pytest_cache",
        "test-results",
        ".DS_Store",
    }

    def clean(info):
        if any(
            part in excluded for part in Path(info.name).parts
        ) or info.name.endswith(".pyc"):
            return None
        if info.issym() or info.islnk():
            raise ValueError("unexpected source archive link")
        return info

    with tarfile.open(artifact, "w:gz") as archive:
        for entry in entries:
            path = ROOT / entry
            if path.exists():
                archive.add(
                    path,
                    arcname=f"document-review-workspace-{VERSION}/{entry}",
                    filter=clean,
                )
    return artifact


with TemporaryDirectory(prefix="document-review-distribution-") as temporary:
    temp = Path(temporary)
    wheel = BACKEND / "dist" / f"document_review_backend-{VERSION}-py3-none-any.whl"
    sdist = BACKEND / "dist" / f"document_review_backend-{VERSION}.tar.gz"
    with ZipFile(wheel) as archive:
        cases = [
            name
            for name in archive.namelist()
            if name.startswith("document_review/sample_data/cases/")
            and name.endswith(".json")
        ]
        assert (
            len(cases) == 12
            and "document_review/sample_data/manifest.json" in archive.namelist()
        )
    requirements = temp / "requirements.txt"
    requirements.write_text(
        run(
            [
                UV,
                "export",
                "--locked",
                "--no-dev",
                "--no-emit-project",
                "--format",
                "requirements-txt",
            ],
            BACKEND,
        ).stdout
    )
    wheel_env = temp / "wheel-env"
    run([UV, "venv", "--python", sys.executable, wheel_env], temp)
    python = wheel_env / "bin/python"
    run([UV, "pip", "sync", "--python", python, requirements], temp)
    run([UV, "pip", "install", "--python", python, "--no-deps", wheel], temp)
    wheel_cases = temp / "wheel-cases"
    wheel_cases.mkdir()
    exercise(python, wheel_cases)
    source_root = temp / "backend-source"
    source_root.mkdir()
    with tarfile.open(sdist) as archive:
        archive.extractall(source_root, filter="data")
    (source,) = source_root.iterdir()
    assert (
        (source / "data/manifest.json").exists()
        and (source / "uv.lock").exists()
        and (source / "fixtures/base.json").exists()
    )
    run(
        [UV, "sync", "--locked", "--no-dev", "--no-editable", "--project", source], temp
    )
    run([source / '.venv/bin/python', '-I', source / 'scripts/generate_data.py', '--check'], temp)
    source_cases = temp / "source-cases"
    source_cases.mkdir()
    exercise(source / ".venv/bin/python", source_cases)
    artifact = source_archive()
    complete = temp / "complete"
    complete.mkdir()
    with tarfile.open(artifact) as archive:
        archive.extractall(complete, filter="data")
    (workspace,) = complete.iterdir()
    frontend = workspace / "frontend"
    assert (workspace / "backend/data/manifest.json").exists() and (
        workspace / ".env.example"
    ).exists()
    run([NPM, "ci"], frontend)
    run([NPM, "run", "typecheck"], frontend)
    run([NPM, "run", "build"], frontend)
print(
    "Fresh locked backend wheel/sdist verified outside checkout: console/module CLI, twelve private exact cases, real human history, source-bound approval/rejection/recovery and model-free API construction. Complete workspace source archive independently npm-ci/typechecked/production-built. No live provider claim."
)

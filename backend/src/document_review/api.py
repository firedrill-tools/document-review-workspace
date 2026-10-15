"""Document review HTTP API and AG-UI endpoint."""

import os
from pathlib import Path

from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from copilotkit import LangGraphAGUIAgent
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agent import build_agent
from .store import Conflict, Workspace


class Decision(BaseModel):
    revision: int
    decision: str
    actor: str


def create_app(workspace_path: Path, include_agent: bool = True) -> FastAPI:
    workspace = Workspace(workspace_path)
    app = FastAPI(title="Document review workspace")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                       allow_methods=["GET", "POST"], allow_headers=["*"])

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
            return workspace.decide(proposal_id, body.revision, body.decision, body.actor)
        except KeyError:
            raise HTTPException(404, "unknown proposal")
        except Conflict as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    if include_agent:
        agent = build_agent(workspace)
        add_langgraph_fastapi_endpoint(
            app=app,
            agent=LangGraphAGUIAgent(name="review_agent", description="Document review copilot", graph=agent),
            path="/agent",
        )
    return app


def main():
    import uvicorn
    path = Path(os.getenv("DOCUMENT_WORKSPACE_FILE", "../workspace.json"))
    uvicorn.run(create_app(path), host="127.0.0.1", port=8124)


if __name__ == "__main__":
    main()

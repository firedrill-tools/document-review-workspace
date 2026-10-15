"use client";

import { CopilotChat } from "@copilotkit/react-core/v2";
import { useCallback, useEffect, useState } from "react";

type Section = { id: string; heading: string; text: string; revision: number; locked: boolean };
type Document = { id: string; title: string; revision: number; sections: Section[] };
type DocumentSummary = { id: string; title: string; revision: number };
type Proposal = {
  id: string; document_id: string; section_id: string; original_text: string;
  replacement_text: string; reason: string; base_section_revision: number;
  revision: number; status: string; decision_actor: string | null;
};
type Detail = { document: Document; proposals: Proposal[] };
const api = process.env.NEXT_PUBLIC_REVIEW_API_URL || "http://localhost:8124";

export default function Page() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedId, setSelectedId] = useState("doc-101");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [actor, setActor] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [listResponse, detailResponse] = await Promise.all([
        fetch(`${api}/documents`, { cache: "no-store" }),
        fetch(`${api}/documents/${selectedId}`, { cache: "no-store" }),
      ]);
      if (!listResponse.ok || !detailResponse.ok) throw new Error("Review API is unavailable");
      setDocuments(await listResponse.json());
      setDetail(await detailResponse.json());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load documents");
    }
  }, [selectedId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function decide(proposal: Proposal, decision: "approve" | "reject") {
    if (!actor.trim()) { setError("Enter your name before deciding."); return; }
    setBusy(true);
    try {
      const response = await fetch(`${api}/proposals/${proposal.id}/decision`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision: proposal.revision, decision, actor: actor.trim() }),
      });
      if (!response.ok) {
        const problem = await response.json();
        throw new Error(problem.detail || "Decision failed");
      }
      setError("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Decision failed");
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  const pending = detail?.proposals.filter((proposal) => proposal.status === "pending") || [];
  const decided = detail?.proposals.filter((proposal) => proposal.status !== "pending") || [];
  const sectionName = (id: string) => detail?.document.sections.find((section) => section.id === id)?.heading || id;

  return <main className="app-shell">
    <header className="topbar">
      <div className="wordmark"><span className="wordmark-mark">D</span> DOCUMENT REVIEW</div>
      <div className="topbar-center">Editorial workspace <span>/</span> October 2026</div>
      <span className="environment">SYNTHETIC DOCUMENTS</span>
    </header>

    <div className="workspace-grid">
      <aside className="document-rail">
        <div className="eyebrow">LIBRARY <span>{String(documents.length).padStart(2, "0")}</span></div>
        <h1>Documents</h1>
        <p className="rail-intro">Select a draft to inspect its committed sections and proposed edits.</p>
        <div className="document-list">
          {documents.map((item) => <button key={item.id}
            className={`document-item ${selectedId === item.id ? "selected" : ""}`}
            onClick={() => { setSelectedId(item.id); setDetail(null); setError(""); }}>
            <span>{item.id.toUpperCase()}</span><strong>{item.title}</strong><small>Revision {item.revision}</small>
          </button>)}
        </div>
        <div className="rail-footer">Local review · one API process</div>
      </aside>

      <section className="document-main">
        {error && <div className="error-banner" role="alert">{error}</div>}
        {!detail ? <div className="empty-state">Loading document…</div> : <>
          <div className="document-heading">
            <div className="eyebrow">DOCUMENT / {detail.document.id.toUpperCase()}</div>
            <h2>{detail.document.title}</h2>
            <div className="document-meta"><span>Committed revision {detail.document.revision}</span><span>{detail.document.sections.length} sections</span></div>
          </div>
          <div className="paper">
            {detail.document.sections.map((section, index) => <article key={section.id} className="section">
              <div className="section-top"><span>0{index + 1} / {section.heading.toUpperCase()}</span>
                <span>{section.locked ? "PROTECTED" : `REV ${section.revision}`}</span></div>
              <h3>{section.heading}</h3><p>{section.text}</p>
            </article>)}
          </div>
          <p className="document-note">Only an approved proposal replaces a section. Other sections retain their text and revision.</p>
        </>}
      </section>

      <aside className="review-panel">
        <div className="review-head"><div className="eyebrow">REVIEW QUEUE</div><h2>Proposed edits</h2>
          <p>Compare the suggestion with the document, then record your decision.</p>
          <label htmlFor="actor">Your name</label><input id="actor" value={actor}
            onChange={(event) => { setActor(event.target.value); setError(""); }} placeholder="Reviewer name" /></div>
        <div className="proposal-list">
          {pending.length === 0 && <p className="quiet">No edits waiting for approval. Ask the copilot to review a section.</p>}
          {pending.map((proposal) => <div className="proposal" key={proposal.id}>
            <div className="proposal-top"><span>{sectionName(proposal.section_id)}</span><span>AWAITING REVIEW</span></div>
            <p className="reason">{proposal.reason}</p>
            <div className="comparison"><div><small>CURRENT</small><p>{proposal.original_text}</p></div>
              <div><small>PROPOSED</small><p>{proposal.replacement_text}</p></div></div>
            <div className="actions"><button className="secondary" disabled={busy} onClick={() => void decide(proposal, "reject")}>Reject</button>
              <button className="primary" disabled={busy} onClick={() => void decide(proposal, "approve")}>Approve edit</button></div>
          </div>)}
          {decided.length > 0 && <div className="history"><div className="eyebrow">DECISIONS</div>
            {decided.map((proposal) => <div className="history-item" key={proposal.id}>
              <strong>{sectionName(proposal.section_id)}</strong><span>{proposal.status} by {proposal.decision_actor}</span></div>)}</div>}
        </div>
        <div className="copilot-panel"><div className="copilot-header"><div className="eyebrow">ASSISTANT</div>
          <h2>Review copilot</h2><p>Ask for a narrow edit. It can prepare proposals but cannot apply them.</p></div>
          <div className="chat-wrap"><CopilotChat agentId="review_agent" className="chat" /></div></div>
      </aside>
    </div>
  </main>;
}

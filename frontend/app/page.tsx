"use client";

import { ReviewChat } from "./review-chat";
import { useCallback, useEffect, useRef, useState } from "react";

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
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("doc-101");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [actor, setActor] = useState("");
  const [loadError, setLoadError] = useState("");
  const [decisionError, setDecisionError] = useState("");
  const [busy, setBusy] = useState(false);
  const selectedIdRef = useRef(selectedId);
  const pendingRead = useRef<AbortController | null>(null);
  selectedIdRef.current = selectedId;

  const refresh = useCallback(async () => {
    if (selectedIdRef.current !== selectedId) return;
    pendingRead.current?.abort();
    const controller = new AbortController();
    pendingRead.current = controller;
    try {
      const [listResponse, detailResponse] = await Promise.all([
        fetch(`${api}/documents`, { cache: "no-store", signal: controller.signal }),
        fetch(`${api}/documents/${selectedId}`, { cache: "no-store", signal: controller.signal }),
      ]);
      if (!listResponse.ok) throw new Error("Review API is unavailable");
      const list: DocumentSummary[] = await listResponse.json();
      if (controller.signal.aborted || selectedIdRef.current !== selectedId) return;
      setDocuments(list);
      if (!list.some(item => item.id === selectedId)) {
        if (!list.length) throw new Error("No documents are available");
        selectedIdRef.current = list[0].id;
        setSelectedId(list[0].id);
        setDetail(null);
        setLoadError("");
        return;
      }
      if (!detailResponse.ok) throw new Error("Review API is unavailable");
      const nextDetail: Detail = await detailResponse.json();
      if (controller.signal.aborted || selectedIdRef.current !== selectedId) return;
      setDetail(nextDetail);
      setLoadError("");
    } catch (cause) {
      if (controller.signal.aborted || selectedIdRef.current !== selectedId) return;
      setLoadError(cause instanceof Error ? cause.message : "Could not load documents");
    }
  }, [selectedId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { window.clearInterval(timer); pendingRead.current?.abort(); };
  }, [refresh]);

  async function decide(proposal: Proposal, decision: "approve" | "reject") {
    if (!actor.trim()) { setDecisionError("Enter your name before deciding."); return; }
    const decidingDocument = proposal.document_id;
    setBusy(true);
    setDecisionError("");
    try {
      const response = await fetch(`${api}/proposals/${proposal.id}/decision`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision: proposal.revision, decision, actor: actor.trim() }),
      });
      if (!response.ok) {
        const problem = await response.json();
        throw new Error(problem.detail || "Decision failed");
      }
      setDecisionError("");
      await refresh();
    } catch (cause) {
      if (selectedIdRef.current === decidingDocument) setDecisionError(cause instanceof Error ? cause.message : "Decision failed");
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  const error = decisionError || loadError;
  const pending = detail?.proposals.filter((proposal) => proposal.status === "pending") || [];
  const decided = detail?.proposals.filter((proposal) => proposal.status !== "pending") || [];
  const visibleDocuments = documents.filter(item => `${item.id} ${item.title}`.toLowerCase().includes(query.trim().toLowerCase()));
  const approvalProblem = (proposal: Proposal) => {
    const section = detail?.document.sections.find(item => item.id === proposal.section_id);
    if (!section || section.revision !== proposal.base_section_revision || section.text !== proposal.original_text) return "Section changed. Read the current document and request a fresh proposal, or reject this one.";
    if (section.locked) return "This section is protected. You can reject the proposal.";
    if (section.revision >= Number.MAX_SAFE_INTEGER || (detail?.document.revision ?? 0) >= Number.MAX_SAFE_INTEGER) return "This document has reached its revision limit. You can reject the proposal.";
    return "";
  };
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
        <label className="document-search">Find document<input value={query} onChange={event => setQuery(event.target.value)} placeholder="Title or document ID" /></label>
        <div className="document-list">
          {visibleDocuments.length === 0 && <p className="quiet">No documents match your search.</p>}
          {visibleDocuments.map((item) => <button key={item.id}
            className={`document-item ${selectedId === item.id ? "selected" : ""}`}
            onClick={() => { selectedIdRef.current = item.id; setSelectedId(item.id); setDetail(null); setDecisionError(""); setLoadError(""); }}>
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
          <label htmlFor="actor">Your name</label><input id="actor" value={actor} maxLength={100}
            onChange={(event) => { setActor(event.target.value); setDecisionError(""); }} placeholder="Reviewer name" /></div>
        <div className="proposal-list">
          {pending.length === 0 && <p className="quiet">No edits waiting for approval. Ask the copilot to review a section.</p>}
          {pending.map((proposal) => <div className="proposal" key={proposal.id}>
            <div className="proposal-top"><span>{sectionName(proposal.section_id)}</span><span>AWAITING REVIEW</span></div>
            <p className="reason">{proposal.reason}</p>
            {approvalProblem(proposal) && <p className="proposal-warning" role="status">{approvalProblem(proposal)}</p>}
            <div className="comparison"><div><small>SOURCE WHEN PROPOSED</small><p>{proposal.original_text}</p></div>
              <div><small>PROPOSED</small><p>{proposal.replacement_text}</p></div></div>
            <div className="actions"><button className="secondary" disabled={busy} onClick={() => void decide(proposal, "reject")}>Reject</button>
              <button className="primary" disabled={busy || Boolean(approvalProblem(proposal))} onClick={() => void decide(proposal, "approve")}>Approve edit</button></div>
          </div>)}
          {decided.length > 0 && <div className="history"><div className="eyebrow">DECISIONS</div>
            {decided.map((proposal) => <div className="history-item" key={proposal.id}>
              <strong>{sectionName(proposal.section_id)}</strong><span>{proposal.status} by {proposal.decision_actor}</span></div>)}</div>}
        </div>
        <div className="copilot-panel"><div className="copilot-header"><div className="eyebrow">ASSISTANT</div>
          <h2>Review copilot</h2><p>Ask for a narrow edit. It can prepare proposals but cannot apply them.</p></div>
          <div className="chat-wrap"><ReviewChat /></div></div>
      </aside>
    </div>
  </main>;
}

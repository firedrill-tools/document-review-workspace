# Working rules

Keep this a standalone synthetic document review app. The CopilotKit/Claude agent may inspect and propose edits, but only the operator decision endpoint can change committed text. Every approval must recheck the target section revision and original text; unrelated sections and documents must remain unchanged. A rejected proposal changes no document text. Protected sections cannot be edited. Do not claim offline tests prove live Claude chat. Add Firedrill only against the qualified new release.


Validate bounded strict document/proposal identities and relationships on read and before write. Decision revisions reject bools/floats/strings/unsafe integers; HTTP extra fields fail. Keep the persistent sidecar lock inode (never unlink it) and unique 0600 atomic temp publication. Advisory ownership covers cooperating POSIX callers, not outside editors. Preserve untouched documents/sections and remove only the current writer's temp on failure. In-memory chat still runs in one API process. Full native completion/raw usage/cancellation, richer data and distribution/browser follow-up remains in PLAN.md; do not claim the 22 domain/API checks qualify native Claude.

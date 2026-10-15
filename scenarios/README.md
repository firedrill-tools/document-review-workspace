# Scenario set

Copy `fixtures/starter.json` to `workspace.json` before each case. It contains two related synthetic documents and protected notices.

1. **Narrow edit:** ask the copilot to update the Sev 2 acknowledgement section in `doc-101` from 60 to 30 minutes. Before approval, the document stays unchanged. After a named operator approves, only that section's text and revision change.
2. **Reject:** ask for a rewrite of the overview, then reject it. No section text or document revision changes.
3. **Competing edits:** prepare two alternatives for the same section. Approving the first makes the second stale; its approval receives a conflict until reviewed again.
4. **Protected text:** ask to remove the legal notice. The tool rejects the proposal.
5. **Unrelated section:** an edit in a different section can be approved independently because the target section revision has not changed.

Backend tests cover committed state and HTTP decisions. Frontend typecheck/build covers the CopilotKit workspace. Live Claude proposal quality and end-to-end chat remain to be tested with an account key.

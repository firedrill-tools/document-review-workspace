import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e-chat", outputDir: "test-results/chat", fullyParallel: false, workers: 1, retries: 0, timeout: 30000,
  use: { baseURL: "http://127.0.0.1:3301", viewport: { width: 1440, height: 1000 }, trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: [
    { command: "uv run --project ../backend --locked python ../backend/tests/browser_chat_api.py", url: "http://127.0.0.1:38124/documents", reuseExistingServer: false, timeout: 30000,
      env: { REVIEW_WEB_ORIGIN: "http://127.0.0.1:3301", LANGSMITH_TRACING: "false", LANGCHAIN_TRACING_V2: "false" }, gracefulShutdown: { signal: "SIGTERM", timeout: 3000 } },
    { command: "npm run start -- --hostname 127.0.0.1 --port 3301", url: "http://127.0.0.1:3301", reuseExistingServer: false, timeout: 60000,
      env: { REVIEW_AGENT_URL: "http://127.0.0.1:38124/agent", NEXT_TELEMETRY_DISABLED: "1", COPILOTKIT_TELEMETRY_DISABLED: "true" }, gracefulShutdown: { signal: "SIGTERM", timeout: 3000 } },
  ],
});

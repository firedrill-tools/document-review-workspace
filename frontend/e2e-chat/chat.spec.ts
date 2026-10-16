import { execFileSync } from "node:child_process";
import { test, expect } from "@playwright/test";
import { copyFileSync, readdirSync, readFileSync, renameSync, rmSync } from "node:fs";
import { resolve } from "node:path";

const file = resolve(".e2e/workspace.json");
const state = () => JSON.parse(readFileSync(file, "utf8"));
const receipts = () => readdirSync(resolve(".e2e/.review-runs")).filter(name => name.endsWith(".json")).map(name => JSON.parse(readFileSync(resolve(".e2e/.review-runs", name), "utf8")));
test.beforeEach(async ({ page }) => {
  copyFileSync(resolve("../fixtures/starter.json"), resolve(".e2e/reset.json"));
  renameSync(resolve(".e2e/reset.json"), file);
  rmSync(resolve(".e2e/.review-runs"), { recursive: true, force: true });
  await page.route(/^https?:/, route => ["127.0.0.1", "localhost"].includes(new URL(route.request().url()).hostname) ? route.continue() : route.abort());
});

test("production CopilotKit native read/proposal and separate named operator approval", async ({ page }, testInfo) => {
  const before = state().documents;
  await page.goto("/");
  const input = page.locator(".chat-wrap textarea");
  await input.fill("Read doc-101 and propose a concise overview.");
  await input.press("Enter");
  await expect(page.locator(".chat-wrap")).toContainText("no document text has changed");
  await expect(page.getByRole("button", { name: "Approve edit" })).toBeVisible();
  expect(state().documents).toEqual(before);
  expect(state().proposals).toHaveLength(1);
  expect(receipts()).toHaveLength(1);
  expect(receipts()[0].provider_observations).toHaveLength(3);
  await expect(page.locator(".chat-wrap script, .chat-wrap a[href^='javascript:']")).toHaveCount(0);
  expect(await page.evaluate(() => "syntheticUnsafe" in window)).toBe(false);
  await page.getByRole("button", { name: "Approve edit" }).click();
  await expect(page.locator(".document-main [role=alert]")).toContainText("Enter your name");
  expect(state().documents).toEqual(before);
  await page.getByLabel("Your name").fill("Avery");
  await page.getByRole("button", { name: "Approve edit" }).click();
  await expect(page.getByText("approved by Avery")).toBeVisible();
  expect(state().documents[0].sections[0].text).toBe(state().proposals[0].replacement_text);
  expect(state().documents[0].sections.slice(1)).toEqual(before[0].sections.slice(1));
  expect(state().documents[1]).toEqual(before[1]);
  await page.screenshot({ path: testInfo.outputPath("native-chat-approved.png"), fullPage: true });
});

test("provider outage and unfinished response remain visible, and a later native turn recovers", async ({ page }) => {
  const before = state().documents;
  await page.goto("/");
  const input = page.locator(".chat-wrap textarea");
  await input.fill("Simulate provider outage for doc-101.");
  await input.press("Enter");
  await expect(page.locator(".chat-wrap [role='alert']")).toContainText(/could not complete/i);
  expect(state().proposals).toEqual([]);
  await input.fill("Simulate unfinished response for doc-101.");
  await input.press("Enter");
  await expect.poll(() => receipts().length).toBe(2);
  await expect(page.locator(".chat-wrap [role='alert']")).toContainText(/could not complete/i);
  expect(state().proposals).toEqual([]);
  await input.fill("Read doc-101 and prepare a complete proposal.");
  await input.press("Enter");
  await expect(page.locator(".chat-wrap")).toContainText("no document text has changed");
  await expect(page.locator(".chat-wrap [role='alert']")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Approve edit" })).toBeVisible();
  expect(state().documents).toEqual(before);
  expect(state().proposals).toHaveLength(1);
  expect(receipts().filter(receipt => receipt.status === "failed")).toHaveLength(2);
});

test("late document reads cannot replace the selection, and successful reload clears an API error", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Incident response handbook", exact: true })).toBeVisible();
  let entered!: () => void;
  let release!: () => void;
  const started = new Promise<void>(resolve => { entered = resolve; });
  const blocked = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/documents/doc-101", async route => {
    const response = await route.fetch();
    entered();
    await blocked;
    try { await route.fulfill({ response }); } catch { /* The old request was aborted after selection. */ }
  });
  try {
    await started;
    await page.getByRole("button", { name: /Customer update template/ }).click();
    await expect(page.getByRole("heading", { name: "Customer update template", exact: true })).toBeVisible();
  } finally { release(); }
  await page.unroute("**/documents/doc-101");
  await expect(page.getByRole("heading", { name: "Customer update template", exact: true })).toBeVisible();
  await page.route("**/documents/doc-101", route => route.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"Controlled unavailable"}' }), { times: 1 });
  await page.getByRole("button", { name: /Incident response handbook/ }).click();
  await expect(page.locator(".document-main [role=alert]")).toContainText("Review API is unavailable");
  await expect(page.getByRole("heading", { name: "Incident response handbook", exact: true })).toBeVisible({ timeout: 8000 });
  await expect(page.locator(".document-main [role=alert]")).toHaveCount(0);
});

function initialize(caseId: string) {
  const reset = resolve(".e2e/reset.json");
  rmSync(reset, { force: true });
  execFileSync(resolve("../backend/.venv/bin/python"), ["-m", "document_review.api", "--init-case", caseId, "--workspace", reset]);
  renameSync(reset, file);
}

test("busy human queue is searchable and one approval preserves every unrelated record", async ({ page }, testInfo) => {
  initialize("busy");
  const before = state();
  await page.goto("/");
  await page.getByLabel("Find document").fill("doc-113");
  await page.getByRole("button", { name: /DOC-113/ }).click();
  await expect(page.getByRole("heading", { name: "Quality review exercise 13", exact: true })).toBeVisible();
  await page.getByLabel("Your name").fill("Avery");
  await page.getByRole("button", { name: "Approve edit" }).click();
  await expect(page.getByText("approved by Avery")).toBeVisible();
  const after = state();
  expect(after.documents.filter((doc: { id: string }) => doc.id !== "doc-113")).toEqual(before.documents.filter((doc: { id: string }) => doc.id !== "doc-113"));
  expect(after.proposals.filter((item: { status: string }) => item.status === "approved")).toHaveLength(13);
  expect(after.proposals).toHaveLength(30);
  const changed = after.proposals.find((item: { decision_actor: string }) => item.decision_actor === "Avery");
  expect(after.proposals.filter((item: { id: string }) => item.id !== changed.id)).toEqual(before.proposals.filter((item: { id: string }) => item.id !== changed.id));
  await page.screenshot({ path: testInfo.outputPath("busy-queue-approved.png"), fullPage: true });
});

test("stale pending edit cannot be approved and explicit rejection preserves the current source", async ({ page }) => {
  initialize("stale-competing-edit");
  const before = state().documents;
  await page.goto("/");
  await expect(page.locator(".proposal-warning")).toContainText("Section changed");
  await expect(page.getByRole("button", { name: "Approve edit" })).toBeDisabled();
  await page.getByLabel("Your name").fill("Avery");
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(page.getByText("rejected by Avery")).toBeVisible();
  expect(state().documents).toEqual(before);
  expect(state().proposals.map((item: { status: string }) => item.status).sort()).toEqual(["approved", "rejected"]);
});

test("noncontiguous document IDs choose a real library entry without a hardcoded default", async ({ page }) => {
  initialize("noncontiguous-ids");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Incident response handbook", exact: true })).toBeVisible();
  await expect(page.locator(".document-heading")).toContainText("DOC-905");
  await page.getByRole("button", { name: /DOC-444/ }).click();
  await expect(page.getByRole("heading", { name: "Customer update template", exact: true })).toBeVisible();
  await expect(page.locator(".document-heading")).toContainText("DOC-444");
  await expect(page.locator(".document-main [role=alert]")).toHaveCount(0);
});

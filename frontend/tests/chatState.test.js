import test from "node:test";
import assert from "node:assert/strict";
import {
  approvalDecisions, asyncTaskToolStatus, isInternalAgentNarration,
  safeImageUrl, safeVisualizationUrl, shouldSendOnEnter,
  userVisibleAssistantContent,
} from "../src/utils/chatState.js";

test("Enter never sends during composition or with Shift", () => {
  assert.equal(shouldSendOnEnter({ key: "Enter" }), true);
  for (const extra of [{ isComposing: true }, { keyCode: 229 }, { shiftKey: true }]) {
    assert.equal(shouldSendOnEnter({ key: "Enter", ...extra }), false);
  }
  assert.equal(shouldSendOnEnter({ key: "Enter" }, true), false);
});

test("approval decisions preserve action count and ordering", () => {
  assert.deepEqual(approvalDecisions([{ name: "a" }, { name: "a" }], "approve"), {
    decisions: [{ type: "approve" }, { type: "approve" }],
  });
  assert.deepEqual(approvalDecisions([], "reject"), { decisions: [] });
});

test("internal agent narration is not eligible for chat rendering", () => {
  for (const content of [
    "I'll delegate this order update.",
    "I'll launch the analysis. Let me first check your preferences.",
    "I'll relaunch the analysis with clearer instructions.",
    "I'll read your preferences file first.",
    "我将委派订单查询。",
  ]) assert.equal(isInternalAgentNarration(content), true);
  assert.equal(isInternalAgentNarration("订单 128 已完成更新。"), false);
});

test("terminal task failure is never shown as success", () => {
  for (const status of ["error", "cancelled", "timeout", "interrupted"]) {
    assert.equal(asyncTaskToolStatus({ done: true, status }), "failed");
  }
  assert.equal(asyncTaskToolStatus({ done: false }), "calling");
  assert.equal(asyncTaskToolStatus({ done: true, status: "success" }), "done");
});

test("stored framework limit errors are converted to a user-facing result", () => {
  const content = userVisibleAssistantContent("Tool call limit reached: run limit exceeded (11/10 calls).");
  assert.match(content, /未能形成完整结论/);
  assert.doesNotMatch(content, /Tool call/i);
  assert.equal(userVisibleAssistantContent("主 Agent：订单已更新。"), "订单已更新。");
});

test("stored chart reports hide artifact IDs and sandbox paths", () => {
  const content = userVisibleAssistantContent("结论。\n◦ **资源 ID**： abcdef0123456789abcdef0123456789\n• **静态 HTML 文件**： /mnt/chart.html\n建议。");
  assert.equal(content, "结论。\n建议。");
});

test("visualizations reject executable and inline document URLs", () => {
  for (const value of ["javascript:alert(1)", "java\nscript:alert(1)", "data:text/html,<script>", "file:///secret", null]) {
    assert.equal(safeVisualizationUrl(value), "");
  }
  assert.equal(safeVisualizationUrl("/artifacts/chart.html"), "/artifacts/chart.html");
  assert.equal(safeVisualizationUrl("https://example.com/chart.png"), "https://example.com/chart.png");
});

test("legacy PNG data renders only as an image, never as a link", () => {
  const png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=";
  assert.equal(safeImageUrl(png), png);
  assert.equal(safeVisualizationUrl(png), "");
  assert.equal(safeImageUrl("/artifacts/chart.png"), "/artifacts/chart.png");
  for (const subtype of ["jpeg", "gif", "webp"]) {
    const url = `data:image/${subtype};base64,YWJj`;
    assert.equal(safeImageUrl(url), url);
  }
});

test("image data rejects executable types, SVG and malformed Base64", () => {
  for (const value of [
    "javascript:alert(1)", "data:text/html;base64,PHNjcmlwdD4=",
    "data:image/svg+xml;base64,PHN2Zz4=", "data:image/png,raw",
    "data:image/png;base64,", "data:image/png;base64,a",
    "data:image/png;base64,@@@@", "data:image/png;base64,YQ===",
    "data:image/png;base64,YQ==<script>", "data:image/png;base64,YQ==\n",
  ]) assert.equal(safeImageUrl(value), "", value);
});

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { computed, ref } from "vue";
import { asyncTaskToolStatus } from "../src/utils/chatState.js";

// 执行真实 setup 逻辑，只替换网络与生命周期；不引入 DOM 或额外测试依赖。
const source = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8")
  .split("<script setup>")[1].split("</script>")[0]
  .replace(/import\s+[\s\S]*?\s+from\s+["'][^"']+["'];/g, "");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function setup(overrides = {}) {
  let unmount;
  const timers = new Map();
  let timerId = 0;
  const dependencies = {
    ref, computed, asyncTaskToolStatus,
    onMounted: () => {}, onUnmounted: (callback) => { unmount = callback; },
    createSession: async () => ({ thread_id: "new" }),
    deleteSession: async () => {},
    getSessions: async () => ({ sessions: [] }),
    getSessionMessages: async (_user, id) => ({ thread_id: id, messages: [] }),
    getAsyncTaskStatus: async () => ({ done: false }),
    streamChat: async () => {}, resumeChat: async () => {},
    localStorage: { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } },
    window: {
      setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
      clearTimeout(id) { timers.delete(id); },
      confirm: () => true,
    },
    ...overrides,
  };
  const app = new Function(...Object.keys(dependencies), `${source}\nreturn {
    threadId, messages, interruptData, queuedMessages, isStreaming, isChangingSession,
    errorMessage, startNewThread, selectSession, streamHandlers, sendMessage,
    resumeInterruptedChat, reloadCurrentSessionMessages, restoreSessionState,
    drainQueuedMessages, startAsyncTaskPolling, lifetimeController,
    readStorage, toggleSidebar, retryAsyncTask,
    isInitializing, isInputLocked, initializeSession, initializationError
  };`)(...Object.values(dependencies));
  app.isInitializing.value = false;
  return { ...app, unmount: () => unmount(), timers };
}

test("session operations serialize selection and double-click creation despite blocked storage", async () => {
  const pending = deferred();
  let creates = 0;
  const app = setup({ createSession: () => { creates += 1; return pending.promise; } });
  const first = app.startNewThread();
  await app.startNewThread();
  await app.selectSession("other");
  assert.equal(creates, 1);
  assert.equal(app.threadId.value, null);
  pending.resolve({ thread_id: "new" });
  await first;
  assert.equal(app.threadId.value, "new");
  assert.equal(app.isChangingSession.value, false);
  assert.equal(app.readStorage("key"), null);
  app.toggleSidebar();
  app.unmount();
});

test("history response cannot overwrite a stream started while fetch was pending", async () => {
  const pending = deferred();
  const stream = deferred();
  const app = setup({ getSessionMessages: () => pending.promise, streamChat: () => stream.promise });
  app.threadId.value = "thread";
  const history = app.reloadCurrentSessionMessages("thread");
  const sending = app.sendMessage("keep me");
  pending.resolve({ messages: [{ id: "old", role: "assistant", content: "old" }] });
  await history;
  assert.equal(app.messages.value[0].content, "keep me");
  app.unmount();
  stream.resolve();
  await sending;
});

test("fragmented delegation args accumulate before parsing", () => {
  const app = setup();
  const handlers = app.streamHandlers();
  handlers.onToolStart({ tool_call_id: "tool", tool_name: "task" });
  handlers.onToolArgs({ tool_call_id: "tool", args: '{"subagent_type":"charts",' });
  handlers.onToolArgs({ tool_call_id: "tool", args: '"description":"采购趋势"}' });
  assert.equal(app.messages.value[0].content, "采购趋势");
  assert.equal(app.messages.value[0].subagentName, "charts");
  handlers.onToolEnd({ tool_call_id: "tool" });
  handlers.onError(new Error("failure"));
  assert.equal(app.messages.value[0].toolStatus, "failed");
  app.unmount();
});

test("interrupt preserves queued messages; failed resume preserves approval", async () => {
  const app = setup({
    streamChat: async (_request, handlers) => handlers.onInterrupt({ thread_id: "thread", interrupt_type: "hitl_approval" }),
    resumeChat: async () => { throw new Error("resume failed"); },
  });
  app.threadId.value = "thread";
  app.queuedMessages.value.push("one", "two");
  await app.drainQueuedMessages();
  assert.deepEqual(app.queuedMessages.value, ["two"]);
  await app.resumeInterruptedChat({ decisions: [] });
  assert.equal(app.interruptData.value.interrupt_type, "hitl_approval");
  assert.deepEqual(app.queuedMessages.value, ["two"]);
  app.unmount();
});

test("failed queued request remains first and does not send following message", async () => {
  let calls = 0;
  const app = setup({ streamChat: async () => { calls += 1; throw new Error("offline"); } });
  app.queuedMessages.value.push("one", "two");
  await app.drainQueuedMessages();
  assert.equal(calls, 1);
  assert.deepEqual(app.queuedMessages.value, ["one", "two"]);
  app.unmount();
});

test("resume addresses the visible interrupt instead of answering another parallel task", async () => {
  const requests = [];
  const app = setup({ resumeChat: async (request) => { requests.push(request); } });
  app.threadId.value = "parallel";
  app.interruptData.value = { interrupt_type: "information_request", interrupt_id: "ask-second" };
  await app.resumeInterruptedChat({ information: "second answer" });
  assert.deepEqual(requests[0].resume, { "ask-second": { information: "second answer" } });
  app.interruptData.value = { interrupt_type: "information_request" };
  await app.resumeInterruptedChat({ information: "legacy answer" });
  assert.deepEqual(requests[1].resume, { information: "legacy answer" });
  app.unmount();
});

test("restored task IDs poll even when the start tool was historically done", async () => {
  const app = setup({ getAsyncTaskStatus: async (id, userId) => {
    assert.equal(id, "task");
    assert.equal(userId, "u1");
    return { done: true, status: "error", error: "failed", delivered: false };
  } });
  app.threadId.value = "thread";
  app.messages.value = [{ id: "tool", role: "delegation", toolName: "start_async_task", asyncTaskId: "task", toolStatus: "done" }];
  app.restoreSessionState({ interrupt: { interrupt_type: "hitl_approval" } });
  await [...app.timers.values()][0]();
  assert.equal(app.messages.value[0].toolStatus, "failed");
  assert.equal(app.interruptData.value.interrupt_type, "hitl_approval");
  app.unmount();
});

test("history interrupt restores waiting tools without pausing independent background tasks", async () => {
  const app = setup({ getSessionMessages: async () => ({
    thread_id: "paused",
    interrupt: { interrupt_type: "information_request", information_needed: "采购数量" },
    messages: [
      { id: "human-input", role: "tool", tool_name: "request_information", tool_status: "calling" },
      { id: "complete", role: "tool", tool_name: "query", tool_status: "done" },
      { id: "background", role: "delegation", tool_name: "start_async_task", tool_status: "calling", async_task_id: "task" },
    ],
  }) });
  await app.selectSession("paused");
  assert.equal(app.messages.value[0].toolStatus, "pending");
  assert.equal(app.messages.value[1].toolStatus, "done");
  assert.equal(app.messages.value[2].toolStatus, "calling");
  assert.equal(app.timers.size, 1);
  app.streamHandlers().onToolResult({ tool_call_id: "human-input", tool_name: "request_information", text: "已补充" });
  assert.equal(app.messages.value[0].toolStatus, "done");
  app.unmount();
});

test("history without interrupt leaves unfinished tools running", async () => {
  const app = setup({ getSessionMessages: async () => ({
    thread_id: "running", messages: [
      { id: "query", role: "tool", tool_name: "query", tool_status: "calling" },
    ],
  }) });
  await app.selectSession("running");
  assert.equal(app.messages.value[0].toolStatus, "calling");
  app.unmount();
});

test("unmount aborts in-flight polling and prevents rescheduling or state writes", async () => {
  const pending = deferred();
  let signal;
  const app = setup({ getAsyncTaskStatus: (_id, _user, options) => { signal = options.signal; return pending.promise; } });
  app.threadId.value = "thread";
  const message = { toolStatus: "calling" };
  app.startAsyncTaskPolling("task", message);
  const polling = [...app.timers.values()][0]();
  app.unmount();
  assert.equal(signal.aborted, true);
  assert.equal(app.lifetimeController.signal.aborted, true);
  pending.resolve({ done: true, status: "success" });
  await polling;
  assert.equal(message.toolStatus, "calling");
  assert.equal(app.timers.size, 0);
});

test("completed task keeps polling while delivery waits for a paused parent", async () => {
  let delivered = false;
  let historyReads = 0;
  const app = setup({
    getAsyncTaskStatus: async () => ({ done: true, status: "success", result: "report", delivered }),
    getSessionMessages: async () => { historyReads += 1; return { messages: [] }; },
  });
  app.threadId.value = "thread";
  app.interruptData.value = { interrupt_type: "hitl_approval" };
  const message = { toolStatus: "calling" };
  app.startAsyncTaskPolling("task", message);
  const tick = async () => {
    const [id, callback] = [...app.timers.entries()][0];
    app.timers.delete(id);
    await callback();
  };
  await tick();
  assert.equal(app.timers.size, 1);
  assert.equal(message.deliveryStatus, "pending");
  assert.equal(app.errorMessage.value, "");
  await tick();
  assert.equal(historyReads, 0);
  app.interruptData.value = null;
  delivered = true;
  await tick();
  assert.equal(historyReads, 1);
  assert.equal(app.timers.size, 0);
  assert.equal(message.deliveryStatus, "delivered");
  app.unmount();
});

test("delivery polling limit exposes retry and retry schedules another query", async () => {
  const app = setup({ getAsyncTaskStatus: async () => ({ done: true, status: "success", delivered: false }) });
  app.threadId.value = "thread";
  app.messages.value = [{ id: "tool", asyncTaskId: "task" }];
  const message = app.messages.value[0];
  app.startAsyncTaskPolling("task", message);
  for (let index = 0; index < 240; index += 1) {
    const [id, callback] = [...app.timers.entries()][0];
    app.timers.delete(id);
    await callback();
  }
  assert.equal(app.timers.size, 0);
  assert.equal(message.deliveryStatus, "retryable");
  app.retryAsyncTask(message);
  assert.equal(app.timers.size, 1);
  assert.equal(message.deliveryStatus, "pending");
  app.unmount();
});

test("bootstrap locks sending until saved session messages are restored", async () => {
  const history = deferred();
  let sends = 0;
  const app = setup({
    getSessions: async () => ({ sessions: [{ thread_id: "saved", title: "采购" }] }),
    localStorage: { getItem: (key) => key.endsWith("current-thread-id") ? "saved" : null, setItem() {} },
    getSessionMessages: () => history.promise,
    streamChat: async () => { sends += 1; },
  });
  const bootstrap = app.initializeSession();
  await Promise.resolve();
  assert.equal(app.isInputLocked.value, true);
  await app.sendMessage("too early");
  assert.equal(sends, 0);
  assert.equal(app.messages.value.length, 0);
  history.resolve({ thread_id: "saved", messages: [{ id: "old", role: "assistant", content: "history" }] });
  await bootstrap;
  assert.equal(app.threadId.value, "saved");
  assert.equal(app.isInputLocked.value, false);
  assert.equal(app.messages.value[0].content, "history");
  app.unmount();
});

test("failed bootstrap stays locked and can retry without creating an early session", async () => {
  let fails = true;
  let creates = 0;
  const app = setup({
    getSessions: async () => { if (fails) throw new Error("offline"); return { sessions: [] }; },
    createSession: async () => { creates += 1; return { thread_id: "new" }; },
  });
  await app.initializeSession();
  assert.equal(app.isInputLocked.value, true);
  assert.equal(app.initializationError.value, "offline");
  assert.equal(creates, 0);
  fails = false;
  await app.initializeSession();
  assert.equal(app.isInputLocked.value, false);
  assert.equal(app.initializationError.value, "");
  assert.equal(creates, 1);
  app.unmount();
});

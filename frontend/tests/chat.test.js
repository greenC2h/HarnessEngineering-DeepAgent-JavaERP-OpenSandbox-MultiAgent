import test from "node:test";
import assert from "node:assert/strict";
import { streamChat } from "../src/api/chat.js";

function mockStream(t, chunks) {
  let body;
  t.mock.method(globalThis, "fetch", async () => {
    body = new ReadableStream({ start(controller) {
      for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
      controller.close();
    } });
    return new Response(body);
  });
  return () => body;
}

test("SSE accepts split CRLF, multiline data, and final EOF event", async (t) => {
  const body = mockStream(t, ['data:{"type":"token",\r', '\ndata: "content":"你好"}\r\n\r', '\ndata:{"type":"done"}']);
  const events = [];
  await streamChat({}, { onToken: (event) => events.push(event.content), onDone: () => events.push("done") });
  assert.deepEqual(events, ["你好", "done"]);
  assert.equal(body().locked, false);
});

test("SSE rejects EOF without terminal event", async (t) => {
  mockStream(t, ['data: {"type":"token","content":"partial"}\n\n']);
  await assert.rejects(streamChat({}, {}), /中断/);
});

test("SSE error is reported and rejects, releasing reader", async (t) => {
  const body = mockStream(t, ['data: {"type":"error","message":"failed"}\n\n']);
  let reported;
  await assert.rejects(streamChat({}, { onError: (error) => { reported = error.message; } }), /failed/);
  assert.equal(reported, "failed");
  assert.equal(body().locked, false);
});

test("non-JSON HTTP errors and request cancellation are preserved", async (t) => {
  const controller = new AbortController();
  t.mock.method(globalThis, "fetch", async (_url, options) => {
    assert.equal(options.signal, controller.signal);
    return new Response("Gateway unavailable", { status: 502 });
  });
  await assert.rejects(streamChat({ signal: controller.signal }, {}), /Gateway unavailable/);
});

/** 采购 Agent SSE 对话接口。 */

function processSseEvent(rawEvent, handlers) {
  const dataLines = rawEvent.split(/\r\n|\r|\n/)
    .filter((line) => line === "data" || line.startsWith("data:"))
    .map((line) => line.slice(5).replace(/^ /, ""));
  if (!dataLines.length) {
    return;
  }

  // 后端以统一的 type 字段区分文本、工具和会话结束事件。
  const data = dataLines.join("\n");
  if (!data.trim()) return;
  const event = JSON.parse(data);
  if (event.type === "token") {
    handlers.onToken?.(event);
  } else if (event.type === "tool_start") {
    handlers.onToolStart?.(event);
  } else if (event.type === "tool_args") {
    handlers.onToolArgs?.(event);
  } else if (event.type === "tool_result") {
    handlers.onToolResult?.(event);
  } else if (event.type === "tool_end") {
    handlers.onToolEnd?.(event);
  } else if (event.type === "interrupt") {
    handlers.onInterrupt?.(event);
  } else if (event.type === "done") {
    handlers.onDone?.(event);
  } else if (event.type === "error") {
    const error = new Error(event.message || "Agent 调用失败");
    handlers.onError?.(error);
    throw error;
  }
  return event.type === "done" || event.type === "interrupt";
}

/**
 * 发送一条消息，并按 SSE 事件调用相应回调。
 *
 * @param {{ message: string, userId: string, username: string, threadId: string | null, signal?: AbortSignal }} request
 * @param {{ onStarted?: Function, onToken?: Function, onToolStart?: Function, onToolArgs?: Function, onToolResult?: Function, onToolEnd?: Function, onDone?: Function, onError?: Function }} handlers
 */
export async function streamChat(request, handlers) {
  return streamResponse("/chat/stream", {
    method: "POST",
    signal: request.signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: request.userId,
      name: request.username,
      message: request.message,
      thread_id: request.threadId,
    }),
  }, handlers);
}

/**
 * 恢复指定会话中已暂停的 LangGraph 执行。
 *
 * @param {{ threadId: string, userId: string, username: string, resume: Object, signal?: AbortSignal }} request
 * @param {{ onStarted?: Function, onToken?: Function, onToolStart?: Function, onToolArgs?: Function, onToolResult?: Function, onToolEnd?: Function, onInterrupt?: Function, onDone?: Function, onError?: Function }} handlers
 */
export async function resumeChat(request, handlers) {
  return streamResponse(`/chat/${encodeURIComponent(request.threadId)}/resume`, {
    method: "POST",
    signal: request.signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: request.userId,
      username: request.username,
      resume: request.resume,
    }),
  }, handlers);
}

async function streamResponse(url, options, handlers) {
  const response = await fetch(url, options);

  if (!response.ok) {
    throw await responseError(response);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("浏览器不支持流式响应");
  }

  const decoder = new TextDecoder();
  let buffer = "";
  let hasTerminalEvent = false;
  try {
    handlers.onStarted?.();
    while (true) {
      const { done, value } = await reader.read();
      if (options.signal?.aborted) throw options.signal.reason;
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

      // 网络分片不保证一个 read 对应一个 SSE 事件，因此保留未完成的尾部。
      // CRLF 必须作为整体处理，包含跨网络分片的 CR/LF。
      let boundary = /\r\n\r\n|\n\n|\r\r/.exec(buffer);
      while (boundary) {
        hasTerminalEvent = processSseEvent(buffer.slice(0, boundary.index), handlers) || hasTerminalEvent;
        buffer = buffer.slice(boundary.index + boundary[0].length);
        boundary = /\r\n\r\n|\n\n|\r\r/.exec(buffer);
      }
      if (done) {
        // 兼容服务端最后一帧未附空行的响应；没有业务终态仍视为断流。
        if (buffer.trim()) hasTerminalEvent = processSseEvent(buffer, handlers) || hasTerminalEvent;
        if (!hasTerminalEvent) throw new Error("连接意外中断，回答可能不完整，请重试。");
        return;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export async function responseError(response) {
  const text = await response.text();
  let detail = text;
  try { detail = JSON.parse(text).detail || text; } catch { /* 网关可能返回纯文本。 */ }
  return new Error(typeof detail === "string" && detail ? detail : `请求失败 (${response.status})`);
}

export async function getSessions(userId, { signal } = {}) {
  const response = await fetch(`/history?user_id=${encodeURIComponent(userId)}`, { signal });
  if (!response.ok) {
    throw new Error("加载历史会话失败");
  }
  return response.json();
}

export async function createSession(userId, { signal } = {}) {
  const response = await fetch(`/history?user_id=${encodeURIComponent(userId)}`, {
    method: "POST",
    signal,
  });
  if (!response.ok) {
    throw new Error("创建会话失败");
  }
  return response.json();
}

export async function getSessionMessages(userId, threadId, { signal } = {}) {
  const response = await fetch(
    `/history/${encodeURIComponent(threadId)}/messages?user_id=${encodeURIComponent(userId)}`,
    { signal },
  );
  if (!response.ok) {
    throw new Error("加载会话消息失败");
  }
  return response.json();
}

export async function deleteSession(userId, threadId, { signal } = {}) {
  const response = await fetch(
    `/history/${encodeURIComponent(threadId)}?user_id=${encodeURIComponent(userId)}`,
    { method: "DELETE", signal },
  );
  if (!response.ok) {
    throw new Error("删除会话失败");
  }
}

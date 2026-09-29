<template>
  <main v-if="isCheckingAuthentication" class="auth-loading" aria-live="polite">正在验证登录状态...</main>
  <AuthView v-else-if="!currentUser" @authenticated="handleAuthenticated" />
  <main v-else class="app-layout">
    <aside class="sidebar" :class="{ collapsed: isSidebarCollapsed }" aria-label="历史会话">
      <div class="sidebar-header">
        <div class="sidebar-heading">
          <p class="eyebrow">ERP PROCUREMENT</p>
          <h1>采购智能助手</h1>
          <p class="current-user">{{ currentUser.username }}</p>
        </div>
        <button
          class="sidebar-toggle"
          type="button"
          :aria-label="isSidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
          :title="isSidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
          @click="toggleSidebar"
        >
          <SidebarSimple :size="18" weight="duotone" aria-hidden="true" />
        </button>
        <button class="new-thread-button" type="button" title="新会话" aria-label="新会话" :disabled="isConversationBusy || queuedMessages.length > 0" @click="startNewThread">
          <span class="new-thread-label">新会话</span>
          <Plus class="new-thread-icon" :size="18" weight="bold" aria-hidden="true" />
        </button>
      </div>

      <label class="session-search">
        <span class="sr-only">搜索会话</span>
        <MagnifyingGlass class="session-search-icon" :size="16" weight="regular" aria-hidden="true" />
        <input v-model.trim="searchKeyword" type="search" placeholder="搜索会话" :disabled="isConversationBusy" />
      </label>

      <nav class="session-list" aria-label="会话列表">
        <p v-if="isLoadingSessions" class="session-hint">正在加载...</p>
        <p v-else-if="filteredSessions.length === 0" class="session-hint">暂无匹配会话</p>
        <article
          v-for="session in filteredSessions"
          :key="session.threadId"
          class="session-item"
          :class="{ active: session.threadId === threadId }"
        >
          <button
            class="session-select"
            type="button"
            :disabled="isConversationBusy || queuedMessages.length > 0"
            :title="session.title"
            :aria-label="session.title"
            @click="selectSession(session.threadId)"
          >
            <span class="session-initial" aria-hidden="true"><ChatCircleText :size="17" weight="duotone" /></span>
            <span class="session-title">{{ session.title }}</span>
            <span class="session-time">{{ formatSessionTime(session.updatedAt) }}</span>
          </button>
          <button
            class="delete-session-button"
            type="button"
            title="删除会话"
            aria-label="删除会话"
            :disabled="isConversationBusy || queuedMessages.length > 0"
            @click="removeSession(session.threadId)"
          ><Trash :size="15" weight="regular" aria-hidden="true" /></button>
        </article>
      </nav>
    </aside>

    <section class="shell">
      <header class="topbar">
        <div>
          <p class="eyebrow">{{ currentUser.username }}的采购对话</p>
          <p class="thread-label">{{ threadLabel }}</p>
        </div>
        <button class="logout-button" type="button" :disabled="isConversationBusy" @click="logout">退出登录</button>
      </header>
      <ChatArea :messages="messages" @retry-task="retryAsyncTask" />
      <div v-if="initializationError" class="queue-notice" role="alert">
        {{ initializationError }}
        <button type="button" :disabled="isBootstrapRunning" @click="initializeSession">重试加载</button>
      </div>
      <InterruptPanel
        v-if="interruptData"
        :key="interruptData.interrupt_id || interruptData.interrupt_type"
        :interrupt-data="interruptData"
        :submitting="isResuming || isStreaming"
        @resume="resumeInterruptedChat"
      />
      <div v-if="queuedMessages.length" class="queue-notice" role="status">
        {{ queuedMessages.length }} 条消息等待发送
        <button v-if="!isConversationBusy" type="button" @click="drainQueuedMessages">继续发送</button>
      </div>
      <InputArea :streaming="isInputLocked" :status-text="inputStatus" :error-message="errorMessage" @send="sendMessage" />
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";

import {
  PhChatCircleText as ChatCircleText,
  PhMagnifyingGlass as MagnifyingGlass,
  PhPlus as Plus,
  PhSidebarSimple as SidebarSimple,
  PhTrash as Trash,
} from "@phosphor-icons/vue";

import {
  createSession,
  deleteSession,
  getSessionMessages,
  getSessions,
  resumeChat,
  streamChat,
} from "./api/chat";
import { getAsyncTaskStatus } from "./api/asyncTasks";
import { getCurrentUser, logout as requestLogout } from "./api/auth";
import AuthView from "./components/AuthView.vue";
import ChatArea from "./components/ChatArea.vue";
import InputArea from "./components/InputArea.vue";
import InterruptPanel from "./components/InterruptPanel.vue";
import { asyncTaskToolStatus } from "./utils/chatState.js";

// 消息列表按事件到达顺序混合保存 user、assistant 和 tool 三种消息。
const USER_STORAGE_KEY = "erp-procurement.current-user";
const CURRENT_THREAD_STORAGE_KEY = "erp-procurement.current-thread-id";
const SIDEBAR_COLLAPSED_STORAGE_KEY = "erp-procurement.sidebar-collapsed";

function readInitialUser() {
  try {
    const saved = localStorage.getItem(USER_STORAGE_KEY);
    const parsed = saved ? JSON.parse(saved) : null;
    // 兼容修复前已写入的 snake_case 身份，同时保证运行时只有一个字段约定。
    const userId = parsed?.userId || parsed?.user_id;
    return userId && parsed?.username ? { userId, username: parsed.username } : null;
  } catch {
    return null;
  }
}

const currentUser = ref(readInitialUser());
const isCheckingAuthentication = ref(true);

function activeUserId() {
  // 测试和旧的嵌入调用没有认证壳时继续使用原演示身份；浏览器正式入口必须先登录。
  return currentUser.value?.userId || "u1";
}

function activeUsername() {
  return currentUser.value?.username || "张三";
}

const threadId = ref(null);
const isSidebarCollapsed = ref(false);
const messages = ref([]);
const isStreaming = ref(false);
const isResuming = ref(false);
const interruptData = ref(null);
const errorMessage = ref("");
const isLoadingSessions = ref(false);
const sessions = ref([]);
const searchKeyword = ref("");
const asyncTaskPollers = new Map();
const completedAsyncTasks = new Map();
const queuedMessages = ref([]);
const isChangingSession = ref(false);
const isInitializing = ref(true);
const isBootstrapRunning = ref(false);
const initializationError = ref("");
const lifetimeController = new AbortController();
const requestOptions = { signal: lifetimeController.signal };
let isDisposed = false;
let sessionRevision = 0;
let conversationRevision = 0;
let sessionsRevision = 0;
let deferredReloadThreadId = null;
const ASYNC_TASK_POLL_INTERVAL_MS = 3_000;
const ASYNC_TASK_MAX_ATTEMPTS = 240;
const canQueueMessageAfterAsyncStart = ref(false);

const threadLabel = computed(() => (
  threadId.value ? `会话 ${threadId.value.slice(0, 8)}` : "新会话"
));

const isConversationBusy = computed(() => (
  isInitializing.value || isChangingSession.value || isStreaming.value || isResuming.value || Boolean(interruptData.value)
));

const isInputLocked = computed(() => (
  isInitializing.value || isChangingSession.value || isResuming.value
  || Boolean(interruptData.value)
  || (isStreaming.value && !canQueueMessageAfterAsyncStart.value)
));

const inputStatus = computed(() => {
  if (isInitializing.value) return initializationError.value ? "请重试加载会话" : "正在恢复会话...";
  if (isChangingSession.value) return "正在加载会话...";
  if (isResuming.value) return "正在提交确认...";
  if (interruptData.value) return "等待补充信息或确认操作";
  if (isStreaming.value) return canQueueMessageAfterAsyncStart.value ? "后台任务已启动，可继续输入" : "正在生成回答...";
  return "";
});

function readStorage(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function writeStorage(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { /* 禁用存储不应阻止当前会话继续使用。 */ }
}

function saveCurrentUser(user) {
  currentUser.value = user;
  writeStorage(USER_STORAGE_KEY, user ? JSON.stringify(user) : null);
}

async function handleAuthenticated(user) {
  saveCurrentUser(user);
  writeStorage(CURRENT_THREAD_STORAGE_KEY, null);
  threadId.value = null;
  sessions.value = [];
  messages.value = [];
  interruptData.value = null;
  initializationError.value = "";
  errorMessage.value = "";
  await initializeSession();
}

async function logout() {
  if (isConversationBusy.value) return;
  try {
    await requestLogout();
  } catch {
    // Cookie 已失效时仍应清理本地状态并回到登录页。
  }
  stopAllAsyncTaskPolling();
  conversationRevision += 1;
  sessionRevision += 1;
  sessionsRevision += 1;
  saveCurrentUser(null);
  writeStorage(CURRENT_THREAD_STORAGE_KEY, null);
  threadId.value = null;
  sessions.value = [];
  messages.value = [];
  interruptData.value = null;
  queuedMessages.value = [];
  initializationError.value = "";
  errorMessage.value = "";
}

const filteredSessions = computed(() => {
  const keyword = searchKeyword.value.toLocaleLowerCase();
  return sessions.value.filter((session) => session.title.toLocaleLowerCase().includes(keyword));
});

function toggleSidebar() {
  isSidebarCollapsed.value = !isSidebarCollapsed.value;
  writeStorage(
    SIDEBAR_COLLAPSED_STORAGE_KEY,
    String(isSidebarCollapsed.value),
  );
}

function createMessageId(role) {
  return `${role}-${crypto.randomUUID()}`;
}

function findMessage(messageId) {
  return messages.value.find((message) => message.id === messageId);
}

function isAsyncDelegation(message) {
  return message.role === "delegation" && message.toolName === "start_async_task";
}

function finishPendingTools(status = "pending") {
  // 没有工具结果不能宣称成功；已提交的后台任务由轮询独立完成。
  for (const message of messages.value) {
    if (["tool", "delegation"].includes(message.role)
      && (message.toolStatus === "calling" || (status === "failed" && message.toolStatus === "pending"))
      && !(isAsyncDelegation(message) && message.asyncTaskId)) {
      message.toolStatus = status;
    }
  }
}

function extractAsyncTaskId(value) {
  const candidates = [];
  const collectStrings = (item) => {
    if (!item) return;
    if (typeof item === "string") {
      candidates.push(item);
    } else if (Array.isArray(item)) {
      item.forEach(collectStrings);
    } else if (typeof item === "object") {
      for (const key of ["task_id", "thread_id", "id"]) {
        if (typeof item[key] === "string") candidates.push(item[key]);
      }
      Object.values(item).forEach(collectStrings);
    }
  };

  try {
    collectStrings(JSON.parse(value));
  } catch {
    collectStrings(value);
  }

  const taskIdPattern = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
  for (const candidate of candidates) {
    const match = String(candidate).match(taskIdPattern);
    if (match) return match[0];
  }
  return null;
}

function stopAllAsyncTaskPolling() {
  for (const stopPolling of asyncTaskPollers.values()) {
    stopPolling();
  }
  asyncTaskPollers.clear();
}

async function reloadCurrentSessionMessages(expectedThreadId) {
  if (isDisposed || !expectedThreadId || threadId.value !== expectedThreadId) return;
  if (isConversationBusy.value || queuedMessages.value.length) {
    deferredReloadThreadId = expectedThreadId;
    return;
  }
  const revision = conversationRevision;
  const response = await getSessionMessages(activeUserId(), expectedThreadId, requestOptions);
  if (isDisposed || threadId.value !== expectedThreadId) return;
  if (revision !== conversationRevision || isConversationBusy.value || queuedMessages.value.length) {
    deferredReloadThreadId = expectedThreadId;
    return;
  }
  if (threadId.value === expectedThreadId) {
    stopAllAsyncTaskPolling();
    messages.value = response.messages.map(normalizeMessage);
    restoreSessionState(response);
  }
}

function startAsyncTaskPolling(taskId, delegationMessage = null) {
  if (isDisposed || !taskId || asyncTaskPollers.has(taskId)) return;

  const parentThreadId = threadId.value;
  let attempts = 0;
  let consecutiveErrors = 0;
  let timerId = null;
  let isStopped = false;
  const controller = new AbortController();

  const stopPolling = () => {
    isStopped = true;
    controller.abort();
    if (timerId !== null) window.clearTimeout(timerId);
    asyncTaskPollers.delete(taskId);
  };

  const poll = async () => {
    attempts += 1;
    try {
      const status = await getAsyncTaskStatus(taskId, activeUserId(), { signal: controller.signal });
      if (isStopped || isDisposed || parentThreadId !== threadId.value) return;
      consecutiveErrors = 0;
      if (status.done) {
        if (delegationMessage) {
          delegationMessage.toolStatus = asyncTaskToolStatus(status);
          delegationMessage.result = status.result || status.error || "后台任务未返回报告";
          delegationMessage.visualization = status.visualization || null;
          delegationMessage.report = status.report || null;
          delegationMessage.deliveryStatus = status.delivered ? "delivered" : "pending";
        }
        if (status.delivered) {
          // 执行终态和投递终态分开：父会话暂停时继续轮询，直到结果真正写入。
          completedAsyncTasks.set(taskId, status);
          stopPolling();
          await reloadCurrentSessionMessages(parentThreadId);
          await loadSessions();
          return;
        }
      }

      if (attempts >= ASYNC_TASK_MAX_ATTEMPTS) {
        stopPolling();
        if (delegationMessage) delegationMessage.deliveryStatus = "retryable";
        if (parentThreadId === threadId.value) {
          errorMessage.value = "后台任务状态或结果同步尚未确认，请点击任务卡片重试。";
        }
        return;
      }
    } catch (error) {
      if (isStopped || isDisposed) return;
      consecutiveErrors += 1;
      if (consecutiveErrors >= 3) {
        stopPolling();
        if (delegationMessage) delegationMessage.deliveryStatus = "retryable";
        if (parentThreadId === threadId.value) {
          errorMessage.value = error.message || "后台任务状态查询失败。";
        }
        return;
      }
    }
    if (!isStopped && !isDisposed) timerId = window.setTimeout(poll, ASYNC_TASK_POLL_INTERVAL_MS);
  };

  asyncTaskPollers.set(taskId, stopPolling);
  timerId = window.setTimeout(poll, ASYNC_TASK_POLL_INTERVAL_MS);
}

function retryAsyncTask(message) {
  if (isDisposed || !messages.value.includes(message) || !message.asyncTaskId) return;
  message.deliveryStatus = "pending";
  errorMessage.value = "";
  startAsyncTaskPolling(message.asyncTaskId, message);
}

async function startNewThread(isBootstrap = false) {
  if (isConversationBusy.value && !(isBootstrap === true && isInitializing.value)) {
    return;
  }
  errorMessage.value = "";
  if (queuedMessages.value.length) return;
  isChangingSession.value = true;
  const revision = ++sessionRevision;
  try {
    // 先创建持久化索引，用户尚未输入消息时也能立即在侧边栏看到“新对话”。
    const session = await createSession(activeUserId(), requestOptions);
    if (isDisposed || revision !== sessionRevision) return;
    stopAllAsyncTaskPolling();
    deferredReloadThreadId = null;
    threadId.value = session.thread_id;
    messages.value = [];
    writeStorage(CURRENT_THREAD_STORAGE_KEY, session.thread_id);
    await loadSessions();
    return true;
  } catch (error) {
    if (isDisposed) return;
    errorMessage.value = error.message || "创建会话失败";
  } finally {
    if (revision === sessionRevision) isChangingSession.value = false;
  }
}

function normalizeMessage(message) {
  return {
    id: message.id,
    role: message.role,
    content: message.content || "",
    author: message.role === "user" ? activeUsername() : undefined,
    toolName: message.tool_name,
    toolStatus: message.tool_status,
    args: message.args || "",
    result: message.text || "",
    source: message.source,
    subagentName: message.source,
    // 委派记录用于异步任务轮询和恢复，不作为用户可见消息呈现。
    isInternalDelegation: message.role === "delegation",
    visualization: message.visualization || null,
    report: message.report || null,
    asyncTaskId: message.async_task_id || "",
  };
}

function restoreAsyncDelegationResults(restoredMessages) {
  const delegations = restoredMessages
    .map((message, index) => ({ message, index }))
    .filter(({ message }) => message.role === "delegation" && !message.result && !message.visualization && !message.report);

  for (const { message: delegation, index } of delegations) {
    const result = restoredMessages
      .slice(index + 1)
      .find((message) => message.role === "assistant"
        && delegation.asyncTaskId && message.asyncTaskId === delegation.asyncTaskId);
    if (result) {
      delegation.result = result.content;
      delegation.visualization = result.visualization || null;
      delegation.report = result.report || null;
    }
  }
}

function restoreSessionState(response) {
  interruptData.value = response.interrupt || null;
  // 历史占位工具默认 calling；有中断时复用实时中断规则，排除独立后台任务。
  if (interruptData.value) finishPendingTools("pending");
  restoreAsyncDelegationResults(messages.value);
  for (const message of messages.value) {
    if (isAsyncDelegation(message) && message.asyncTaskId) {
      const completed = completedAsyncTasks.get(message.asyncTaskId);
      if (completed) {
        message.toolStatus = asyncTaskToolStatus(completed);
        message.result = completed.result || completed.error || message.result;
        message.visualization = completed.visualization || message.visualization;
        message.report = completed.report || message.report;
      } else {
        // 历史的 done 可能仅表示启动工具完成，必须查询后台任务的真实终态。
        message.toolStatus = "calling";
        startAsyncTaskPolling(message.asyncTaskId, message);
      }
    }
  }
}

function parseTaskArguments(argsText) {
  if (!argsText) {
    return null;
  }
  try {
    return JSON.parse(argsText);
  } catch {
    // 兼容旧版本 SSE 使用的 Python dict 字符串，避免历史运行中的任务摘要丢失。
    try {
      const normalized = String(argsText)
        .replace(/\bNone\b/g, "null")
        .replace(/\bTrue\b/g, "true")
        .replace(/\bFalse\b/g, "false")
        .replace(/'([^']*)'/g, '"$1"');
      return JSON.parse(normalized);
    } catch {
      return null;
    }
  }
}

function inferSubagentName(argsText) {
  const args = parseTaskArguments(argsText);
  return typeof args?.subagent_type === "string" ? args.subagent_type : "";
}

function taskDescription(argsText) {
  const args = parseTaskArguments(argsText);
  return typeof args?.description === "string" ? args.description : "";
}

async function loadSessions() {
  if (isDisposed) return;
  const revision = ++sessionsRevision;
  isLoadingSessions.value = true;
  try {
    const response = await getSessions(activeUserId(), requestOptions);
    if (isDisposed || revision !== sessionsRevision) return;
    sessions.value = response.sessions.map((session) => ({
      threadId: session.thread_id,
      title: session.title,
      updatedAt: session.updated_at,
    }));
    return true;
  } catch (error) {
    if (isDisposed || revision !== sessionsRevision) return;
    errorMessage.value = error.message || "加载历史会话失败";
  } finally {
    if (revision === sessionsRevision) isLoadingSessions.value = false;
  }
}

async function selectSession(selectedThreadId, isBootstrap = false) {
  if (selectedThreadId === threadId.value
    || (isConversationBusy.value && !(isBootstrap === true && isInitializing.value))
    || queuedMessages.value.length) {
    return;
  }
  errorMessage.value = "";
  isChangingSession.value = true;
  const revision = ++sessionRevision;
  try {
    const response = await getSessionMessages(activeUserId(), selectedThreadId, requestOptions);
    if (isDisposed || revision !== sessionRevision) return;
    stopAllAsyncTaskPolling();
    deferredReloadThreadId = null;
    threadId.value = response.thread_id;
    messages.value = response.messages.map(normalizeMessage);
    restoreSessionState(response);
    writeStorage(CURRENT_THREAD_STORAGE_KEY, selectedThreadId);
    return true;
  } catch (error) {
    if (isDisposed) return;
    errorMessage.value = error.message || "加载会话消息失败";
  } finally {
    if (revision === sessionRevision) isChangingSession.value = false;
  }
}

async function removeSession(selectedThreadId) {
  if (isConversationBusy.value || queuedMessages.value.length || !window.confirm("确定删除这个会话吗？")) {
    return;
  }
  isChangingSession.value = true;
  try {
    await deleteSession(activeUserId(), selectedThreadId, requestOptions);
    if (isDisposed) return;
    if (threadId.value === selectedThreadId) {
      threadId.value = null;
      messages.value = [];
      stopAllAsyncTaskPolling();
      deferredReloadThreadId = null;
      writeStorage(CURRENT_THREAD_STORAGE_KEY, null);
    }
    await loadSessions();
  } catch (error) {
    if (isDisposed) return;
    errorMessage.value = error.message || "删除会话失败";
  } finally {
    isChangingSession.value = false;
  }
}

function formatSessionTime(value) {
  if (!value || Number.isNaN(new Date(value).getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function streamHandlers() {
  return {
    onToken(event) {
      // 服务端为一段连续助手文本分配同一个 message_id，可直接增量追加。
      let message = findMessage(event.message_id);
      if (!message) {
        message = {
          id: event.message_id,
          role: "assistant",
          content: "",
          source: event.source || "main",
        };
        messages.value.push(message);
      }
      message.content += event.content || "";
      if (event.source && event.source !== "main" && event.source !== "subagent") {
        const pendingDelegation = [...messages.value]
          .reverse()
          .find((item) => item.role === "delegation" && item.toolStatus === "calling");
        if (pendingDelegation && !pendingDelegation.subagentName) {
          pendingDelegation.subagentName = event.source;
          pendingDelegation.source = event.source;
        }
      }
    },
    onToolStart(event) {
      if (findMessage(event.tool_call_id)) {
        return;
      }
      messages.value.push({
        id: event.tool_call_id,
        role: ["task", "start_async_task"].includes(event.tool_name) ? "delegation" : "tool",
        isInternalDelegation: ["task", "start_async_task"].includes(event.tool_name),
        toolName: event.tool_name,
        args: "",
        result: "",
        toolStatus: "calling",
        source: event.source || "main",
        subagentName: event.subagent_name || "",
        visualization: null,
        report: null,
        asyncTaskId: "",
      });
    },
    onToolArgs(event) {
      const message = findMessage(event.tool_call_id);
      if (message) {
        message.args += event.args || "";
        if (message.role === "delegation") {
          const subagentName = event.subagent_name || inferSubagentName(message.args);
          if (subagentName) {
            message.subagentName = subagentName;
            message.source = subagentName;
          }
          const description = taskDescription(message.args);
          if (description) {
            message.content = description;
          }
          return;
        }
      }
    },
    onToolResult(event) {
      const message = findMessage(event.tool_call_id);
      if (message) {
        const isAsyncTaskStart = event.tool_name === "start_async_task";
        if (!isAsyncTaskStart) {
          message.toolStatus = event.error || event.status === "error" ? "failed" : "done";
        }
        if (message.role === "delegation" && event.subagent_name) {
          message.subagentName = event.subagent_name;
          message.source = event.subagent_name;
        }
        if (message.role !== "delegation") {
          message.result = event.text || "工具未返回文本结果";
          message.visualization = event.visualization || null;
        } else if (event.tool_name === "task") {
          message.result = event.text || "子 Agent 未返回最终报告";
        }
        if (message.role === "delegation" && !message.subagentName) {
          const subagentName = inferSubagentName(message.args);
          if (subagentName) {
            message.subagentName = subagentName;
          }
        }
        if (event.source && !message.subagentName) {
          message.source = event.source;
        }
        if (event.tool_name === "start_async_task") {
          canQueueMessageAfterAsyncStart.value = true;
          const asyncTaskId = extractAsyncTaskId(event.text);
          message.asyncTaskId = asyncTaskId || "";
          if (asyncTaskId) {
            // 工具返回只说明后台任务已提交；轮询到终态结果前，卡片必须保持运行中。
            startAsyncTaskPolling(asyncTaskId, message);
          } else {
            message.toolStatus = "failed";
            message.result = "后台任务创建失败：未返回可查询的任务 ID。";
          }
        }
      }
    },
    onToolEnd(event) {
      const message = findMessage(event.tool_call_id);
      if (message && !isAsyncDelegation(message) && message.toolStatus === "calling") {
        message.toolStatus = "pending";
      }
    },
    onInterrupt(event) {
      finishPendingTools("pending");
      interruptData.value = event;
      if (event.thread_id) {
        threadId.value = event.thread_id;
        writeStorage(CURRENT_THREAD_STORAGE_KEY, event.thread_id);
      }
    },
    onDone(event) {
      finishPendingTools();
      if (event.thread_id) {
        threadId.value = event.thread_id;
        writeStorage(CURRENT_THREAD_STORAGE_KEY, event.thread_id);
      }
      if (!event.interrupted) {
        interruptData.value = null;
      }
    },
    onError(error) {
      finishPendingTools("failed");
      errorMessage.value = error.message;
    },
  };
}

async function sendMessage(content) {
  if (isDisposed) return;
  if (isConversationBusy.value) {
    if (isStreaming.value && canQueueMessageAfterAsyncStart.value && !interruptData.value) {
      messages.value.push({
        id: createMessageId("user"),
        role: "user",
        content,
        author: activeUsername(),
      });
      queuedMessages.value.push(content);
    }
    return;
  }
  if (queuedMessages.value.length) {
    messages.value.push({ id: createMessageId("user"), role: "user", content, author: activeUsername() });
    queuedMessages.value.push(content);
    await drainQueuedMessages();
    return;
  }
  await sendMessageNow(content);
}

async function drainQueuedMessages() {
  if (isDisposed || isConversationBusy.value || !queuedMessages.value.length) return;
  await sendMessageNow(queuedMessages.value.shift(), true);
}

async function finishConversationTurn(hasSucceeded) {
  if (isDisposed) return;
  const revision = conversationRevision;
  if (threadId.value) await loadSessions();
  if (isDisposed || isConversationBusy.value || revision !== conversationRevision) return;
  if (hasSucceeded && queuedMessages.value.length) {
    await drainQueuedMessages();
  } else if (hasSucceeded && deferredReloadThreadId && !queuedMessages.value.length) {
    const target = deferredReloadThreadId;
    deferredReloadThreadId = null;
    try { await reloadCurrentSessionMessages(target); }
    catch (error) { if (!isDisposed) errorMessage.value = error.message; }
  }
}

async function sendMessageNow(content, isAlreadyVisible = false) {
  if (isDisposed) return;
  conversationRevision += 1;
  let hasSucceeded = false;
  if (!isAlreadyVisible) {
    messages.value.push({
      id: createMessageId("user"),
      role: "user",
      content,
      author: activeUsername(),
    });
  }
  errorMessage.value = "";
  isStreaming.value = true;

  try {
    await streamChat(
      {
        message: content,
        userId: activeUserId(),
        username: activeUsername(),
        threadId: threadId.value,
        signal: lifetimeController.signal,
      },
      streamHandlers(),
    );
    hasSucceeded = true;
  } catch (error) {
    if (isDisposed) return;
    // 队列消息失败后保留原位置，等待用户明确重试，不在错误后自动继续发送。
    if (isAlreadyVisible) queuedMessages.value.unshift(content);
    finishPendingTools("failed");
    errorMessage.value = error.message || "请求失败，请稍后重试";
  } finally {
    isStreaming.value = false;
    canQueueMessageAfterAsyncStart.value = false;
    await finishConversationTurn(hasSucceeded);
  }
}

async function resumeInterruptedChat(resume) {
  if (isDisposed || !threadId.value || isStreaming.value || isResuming.value || !interruptData.value) {
    return;
  }
  errorMessage.value = "";
  isResuming.value = true;
  conversationRevision += 1;
  const previousInterrupt = interruptData.value;
  // 用户已经提交恢复数据后立即收起面板；若恢复失败，catch 会把原中断恢复显示。
  interruptData.value = null;
  let hasSucceeded = false;
  try {
    await resumeChat(
      {
        threadId: threadId.value,
        userId: activeUserId(),
        username: activeUsername(),
        // 并行子任务可能各自中断，必须按 ID 只恢复当前显示的那一项。
        resume: previousInterrupt.interrupt_id ? { [previousInterrupt.interrupt_id]: resume } : resume,
        signal: lifetimeController.signal,
      },
      streamHandlers(),
    );
    hasSucceeded = true;
  } catch (error) {
    if (isDisposed) return;
    interruptData.value = previousInterrupt;
    finishPendingTools("failed");
    errorMessage.value = error.message || "恢复对话失败，请稍后重试";
  } finally {
    isResuming.value = false;
    await finishConversationTurn(hasSucceeded);
  }
}

async function initializeSession() {
  if (isDisposed || isBootstrapRunning.value) return;
  isInitializing.value = true;
  isBootstrapRunning.value = true;
  initializationError.value = "";
  errorMessage.value = "";
  isSidebarCollapsed.value = readStorage(SIDEBAR_COLLAPSED_STORAGE_KEY) === "true";
  try {
    if (!await loadSessions()) throw new Error(errorMessage.value || "加载会话失败");
    if (isDisposed) return;
    if (!threadId.value) {
      const savedThreadId = readStorage(CURRENT_THREAD_STORAGE_KEY);
      // 初始化完成前禁止发送或切换，避免恢复的历史覆盖用户刚输入的消息。
      const hasRestoredSession = savedThreadId && sessions.value.some((session) => session.threadId === savedThreadId);
      const succeeded = hasRestoredSession
        ? await selectSession(savedThreadId, true)
        : await startNewThread(true);
      if (!succeeded) throw new Error(errorMessage.value || "恢复会话失败");
    }
    if (!isDisposed) isInitializing.value = false;
  } catch (error) {
    if (!isDisposed) initializationError.value = error.message || "初始化失败，请重试";
  } finally {
    isBootstrapRunning.value = false;
  }
}

onMounted(async () => {
  try {
    const verifiedUser = await getCurrentUser({ signal: lifetimeController.signal });
    if (!isDisposed) {
      saveCurrentUser(verifiedUser);
      await initializeSession();
    }
  } catch {
    if (!isDisposed) {
      // 本地缓存不是登录凭据；Cookie 校验失败就直接回到登录入口。
      saveCurrentUser(null);
      writeStorage(CURRENT_THREAD_STORAGE_KEY, null);
    }
  } finally {
    if (!isDisposed) isCheckingAuthentication.value = false;
  }
});

onUnmounted(() => {
  isDisposed = true;
  lifetimeController.abort();
  stopAllAsyncTaskPolling();
});
</script>

<template>
  <section ref="messageList" class="messages" aria-live="polite" aria-label="对话消息" @scroll="updateScrollPosition">
    <div v-if="visibleMessages.length === 0" class="empty-state">
      <p>今天需要处理什么采购问题？</p>
      <p>可以查询订单、整理采购需求，或分析采购数据。</p>
    </div>
    <MessageItem v-for="message in visibleMessages" :key="message.id" :message="message" @retry-task="emit('retry-task', message)" />
  </section>
  <button v-if="hasNewMessages" class="new-messages-button" type="button" @click="scrollToBottom">查看新消息 ↓</button>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue";

import MessageItem from "./MessageItem.vue";
import { isInternalAgentNarration } from "../utils/chatState.js";

const props = defineProps({
  messages: {
    type: Array,
    required: true,
  },
});

const messageList = ref(null);
const emit = defineEmits(["retry-task"]);
const isNearBottom = ref(true);
const hasNewMessages = ref(false);
const visibleMessages = computed(() => (
  // 工具调用和委派卡片默认收起，由 MessageItem 提供按需展开的参数、任务和结果。
  // 仅过滤模型泄露的内部旁白；用户需要能够检查主 Agent 与子 Agent 的执行边界。
  props.messages.filter((message) => (
    !isInternalAgentNarration(message.content)
  ))
));

function updateScrollPosition() {
  const element = messageList.value;
  if (!element) return;
  isNearBottom.value = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
  if (isNearBottom.value) hasNewMessages.value = false;
}

function scrollToBottom() {
  if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight;
  isNearBottom.value = true;
  hasNewMessages.value = false;
}

// 用户回看历史时保留位置；替换会话或接近底部时才跟随新内容。
watch(
  () => props.messages,
  async (value, previous) => {
    const shouldFollow = isNearBottom.value || value !== previous;
    await nextTick();
    if (shouldFollow) scrollToBottom();
    else hasNewMessages.value = true;
  },
  { deep: true },
);
</script>

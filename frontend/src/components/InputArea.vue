<template>
  <form class="composer" @submit.prevent="send">
    <label class="sr-only" for="message">消息</label>
    <textarea
      id="message"
      v-model="message"
      rows="2"
      placeholder="输入采购问题..."
      :disabled="streaming"
      @compositionstart="isComposing = true"
      @compositionend="isComposing = false"
      @keydown="handleKeydown"
    ></textarea>
    <div class="composer-footer">
      <span class="status" :class="{ error: errorMessage }" role="status">
        {{ errorMessage || statusText || 'Enter 发送 · Shift+Enter 换行' }}
      </span>
      <button class="send-button" type="submit" :disabled="streaming || !message.trim()">
        <span>发送</span>
        <PaperPlaneTilt :size="16" weight="fill" aria-hidden="true" />
      </button>
    </div>
  </form>
</template>

<script setup>
import { ref } from "vue";
import { PhPaperPlaneTilt as PaperPlaneTilt } from "@phosphor-icons/vue";
import { shouldSendOnEnter } from "../utils/chatState.js";

const props = defineProps({
  streaming: Boolean,
  statusText: { type: String, default: "" },
  errorMessage: {
    type: String,
    default: "",
  },
});

const emit = defineEmits(["send"]);
const message = ref("");
const isComposing = ref(false);

function handleKeydown(event) {
  if (!shouldSendOnEnter(event, isComposing.value)) return;
  event.preventDefault();
  send();
}

function send() {
  const content = message.value.trim();
  if (!content || props.streaming || isComposing.value) {
    return;
  }
  emit("send", content);
  message.value = "";
}
</script>

<template>
  <section class="interrupt-panel" :class="`interrupt-${interruptData.interrupt_type}`" aria-live="assertive">
    <template v-if="isInformationRequest">
      <h2>需要补充信息</h2>
      <p v-if="informationNeeded" class="interrupt-value">{{ informationNeeded }}</p>
      <p v-if="informationContext" class="interrupt-label">当前上下文</p>
      <pre v-if="informationContext" class="interrupt-data">{{ informationContext }}</pre>
      <label class="sr-only" for="interrupt-supplement">补充信息</label>
      <textarea
        id="interrupt-supplement"
        v-model="supplement"
        rows="3"
        placeholder="请输入需要补充的信息"
        :disabled="submitting"
        @compositionstart="isComposing = true"
        @compositionend="isComposing = false"
        @keydown="handleKeydown"
      ></textarea>
      <button class="interrupt-submit" type="button" :disabled="!supplement.trim() || submitting" @click="submitSupplement">
        {{ submitting ? '提交中...' : '提交补充信息' }}
      </button>
    </template>

    <template v-else-if="interruptData.interrupt_type === 'hitl_approval'">
      <h2>需要确认订单操作</h2>
      <div v-for="(action, index) in interruptData.action_requests" :key="action.id || index" class="interrupt-action">
        <strong>{{ action.name }}</strong>
        <pre>{{ formatActionArgs(action.args) }}</pre>
      </div>
      <div class="interrupt-actions">
        <button class="interrupt-approve" type="button" :disabled="submitting" @click="submitDecision('approve')">
          同意全部执行
        </button>
        <button class="interrupt-reject" type="button" :disabled="submitting" @click="submitDecision('reject')">
          拒绝全部执行
        </button>
      </div>
    </template>

    <template v-else>
      <h2>对话已暂停</h2>
      <pre class="interrupt-data">{{ interruptData.interrupt_value || '等待人工处理' }}</pre>
    </template>
  </section>
</template>

<script setup>
import { computed, ref } from "vue";
import { approvalDecisions, shouldSendOnEnter } from "../utils/chatState.js";

const props = defineProps({
  interruptData: {
    type: Object,
    required: true,
  },
  submitting: Boolean,
});

const emit = defineEmits(["resume"]);
const supplement = ref("");
const isComposing = ref(false);
function handleKeydown(event) {
  if (!shouldSendOnEnter(event, isComposing.value)) return;
  event.preventDefault();
  submitSupplement();
}
const isInformationRequest = computed(() => props.interruptData.interrupt_type === "information_request");
const informationNeeded = computed(() =>
  props.interruptData.information_needed || "",
);
const informationContext = computed(() =>
  props.interruptData.context || "",
);

function submitSupplement() {
  if (!supplement.value.trim() || props.submitting || isComposing.value) {
    return;
  }
  emit("resume", { information: supplement.value.trim() });
}

function submitDecision(type) {
  if (props.submitting) {
    return;
  }
  const payload = approvalDecisions(props.interruptData.action_requests, type);
  if (payload.decisions.length) emit("resume", payload);
}

function formatActionArgs(args) {
  return JSON.stringify(args || {}, null, 2);
}
</script>

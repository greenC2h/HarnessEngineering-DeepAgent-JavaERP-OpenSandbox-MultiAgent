<template>
  <article class="message" :class="messageKind">
    <div class="message-identity">
      <span class="message-avatar" aria-hidden="true">
        <component :is="avatarIcon" :size="18" weight="duotone" />
      </span>
      <span class="message-meta">{{ author }}</span>
    </div>

    <template v-if="message.role === 'delegation'">
      <div class="delegation-summary">
        <span class="delegation-title">{{ agentName }}</span>
        <span class="delegation-status" :class="{ 'status-failed': message.toolStatus === 'failed' }">{{ toolStatusLabel }}</span>
        <button
          v-if="message.content || message.result || message.visualization"
          class="tool-toggle"
          type="button"
          :aria-expanded="isDetailsExpanded"
          @click="isDetailsExpanded = !isDetailsExpanded"
        >
          <component :is="isDetailsExpanded ? CaretUp : CaretDown" :size="14" weight="bold" aria-hidden="true" />
          <span>{{ isDetailsExpanded ? '收起详情' : '展开详情' }}</span>
        </button>
      </div>
      <span v-if="message.deliveryStatus === 'pending'" class="delegation-status">等待同步到会话…</span>
      <button v-else-if="message.deliveryStatus === 'retryable'" class="tool-toggle" type="button" @click="emit('retry-task')">重试查询 / 同步结果</button>
      <div v-if="isDetailsExpanded && message.content" class="delegation-details">
        <div class="delegation-label">任务</div>
        <div class="markdown-content" v-html="renderedContent"></div>
      </div>
      <div v-if="isDetailsExpanded && message.result" class="delegation-details">
        <div class="delegation-label">结果</div>
        <div class="markdown-content" v-html="renderedResult"></div>
      </div>
      <div v-if="isDetailsExpanded && message.visualization" class="delegation-details">
        <div class="delegation-label">图表</div>
        <a
          v-if="message.visualization.kind === 'link' && visualizationSrc"
          class="visualization-link"
          :href="visualizationSrc"
          target="_blank"
          rel="noopener"
        >
          {{ message.visualization.label || '打开 HTML 图表' }}
        </a>
        <a
          v-if="visualizationDownload"
          class="visualization-download"
          :href="visualizationDownload"
          download
        ><DownloadSimple :size="15" weight="bold" aria-hidden="true" />下载 HTML</a>
      </div>
    </template>
    <template v-else-if="message.role === 'tool'">
      <div class="tool-summary">
        <span class="tool-status" :class="{ 'status-failed': message.toolStatus === 'failed' }">{{ toolStatusLabel }}</span>
        <button
          v-if="toolDetails"
          class="tool-toggle"
          type="button"
          :aria-expanded="isToolDetailsExpanded"
          @click="isToolDetailsExpanded = !isToolDetailsExpanded"
        >
          <component :is="isToolDetailsExpanded ? CaretUp : CaretDown" :size="14" weight="bold" aria-hidden="true" />
          <span>{{ isToolDetailsExpanded ? '收起详情' : '展开详情' }}</span>
        </button>
      </div>
      <div v-if="message.visualization" class="visualization-preview">
        <span class="visualization-label">{{ agentName }} visualization</span>
        <img
          v-if="message.visualization.kind === 'image' && visualizationImageSrc"
          class="visualization-image"
          :src="visualizationImageSrc"
          alt="Generated visualization"
        />
        <a
          v-else-if="message.visualization.kind === 'link' && visualizationSrc"
          class="visualization-link"
          :href="visualizationSrc"
          target="_blank"
          rel="noopener"
        >
          <span>{{ message.visualization.label || '打开 HTML 图表' }}</span>
          <ArrowUpRight :size="15" weight="bold" aria-hidden="true" />
        </a>
        <a
          v-if="visualizationDownload"
          class="visualization-download"
          :href="visualizationDownload"
          download
        >
          <span>下载 HTML</span>
          <DownloadSimple :size="15" weight="bold" aria-hidden="true" />
        </a>
      </div>
      <div v-if="isToolDetailsExpanded" class="tool-details">
        <div class="tool-detail-block">
          <div class="tool-detail-label">参数</div>
          <pre>{{ message.args || "{}" }}</pre>
        </div>
        <div v-if="message.result || message.visualization" class="tool-detail-block">
          <div class="tool-detail-label">结果</div>
          <pre v-if="!message.visualization">{{ message.result }}</pre>
          <span v-else>可视化资源已返回，请查看上方入口。</span>
        </div>
      </div>
    </template>
    <template v-else-if="message.role === 'assistant'">
      <div v-if="renderedContent" class="message-content markdown-content" v-html="renderedContent"></div>
      <div v-if="message.visualization" class="visualization-preview">
        <span class="visualization-label">图表交付物</span>
        <img
          v-if="message.visualization.kind === 'image' && visualizationImageSrc"
          class="visualization-image"
          :src="visualizationImageSrc"
          alt="Generated visualization"
        />
        <a
          v-else-if="message.visualization.kind === 'link' && visualizationSrc"
          class="visualization-link"
          :href="visualizationSrc"
          target="_blank"
          rel="noopener"
        >
          <span>{{ message.visualization.label || '打开 HTML 图表' }}</span>
          <ArrowUpRight :size="15" weight="bold" aria-hidden="true" />
        </a>
        <a
          v-if="visualizationDownload"
          class="visualization-download"
          :href="visualizationDownload"
          download
        >
          <span>下载 HTML</span>
          <DownloadSimple :size="15" weight="bold" aria-hidden="true" />
        </a>
      </div>
      <div v-if="reportDownload" class="visualization-preview report-download">
        <span class="visualization-label">采购分析报告</span>
        <a class="visualization-download" :href="reportDownload" download="procurement-analysis.md">
          <span>{{ message.report.label || '下载采购分析报告' }}</span>
          <DownloadSimple :size="15" weight="bold" aria-hidden="true" />
        </a>
      </div>
    </template>
    <div v-else class="message-content">{{ message.content }}</div>
  </article>
</template>

<script setup>
import { computed, ref } from "vue";

import {
  PhArrowUpRight as ArrowUpRight,
  PhCaretDown as CaretDown,
  PhCaretUp as CaretUp,
  PhDownloadSimple as DownloadSimple,
  PhRobot as Robot,
  PhSparkle as Sparkle,
  PhUserCircle as UserCircle,
  PhWrench as Wrench,
} from "@phosphor-icons/vue";

import { renderMarkdown } from "../utils/markdown";
import { safeImageUrl, safeVisualizationUrl, userVisibleAssistantContent } from "../utils/chatState.js";

const props = defineProps({
  message: {
    type: Object,
    required: true,
  },
});

const isToolDetailsExpanded = ref(false);
const emit = defineEmits(["retry-task"]);
const isDetailsExpanded = ref(false);
const visualizationSrc = computed(() => safeVisualizationUrl(props.message.visualization?.src));
const visualizationImageSrc = computed(() => safeImageUrl(props.message.visualization?.src));
const visualizationDownload = computed(() => safeVisualizationUrl(props.message.visualization?.download_src));
const reportDownload = computed(() => safeVisualizationUrl(props.message.report?.download_src));
const toolStatusLabel = computed(() => ({
  calling: "正在处理", done: "已完成", failed: "执行失败", pending: "等待处理",
  interrupted: "等待确认", cancelled: "已取消", timeout: "已超时",
}[props.message.toolStatus] || "等待结果"));

const messageKind = computed(() => {
  if (props.message.role === "user") {
    return "user";
  }
  if (props.message.role === "delegation") {
    return "subagent-task";
  }
  if (props.message.role === "tool") {
    return "main-tool";
  }
  return "main-agent";
});

const agentName = computed(() => {
  if (props.message.subagentName && props.message.subagentName !== "main") {
    return props.message.subagentName;
  }
  if (props.message.source && props.message.source !== "main") {
    return props.message.source;
  }
  return props.message.role === "delegation" ? "subagent" : "main";
});

const avatarIcon = computed(() => {
  if (messageKind.value === "user") {
    return UserCircle;
  }
  if (messageKind.value === "subagent-task") {
    return Robot;
  }
  if (messageKind.value === "main-tool") {
    return Wrench;
  }
  return Sparkle;
});

const author = computed(() => {
  if (props.message.role === "user") {
    return props.message.author;
  }
  if (props.message.role === "tool") {
    return `主 Agent 工具 · ${props.message.toolName || "MCP tool"}`;
  }
  if (props.message.role === "delegation") {
    return `子 Agent 任务 · ${agentName.value}`;
  }
  return "采购助手";
});

const toolDetails = computed(() => {
  const details = [];
  details.push(`参数\n${props.message.args || "无"}`);
  if (props.message.result) {
    details.push(
      props.message.visualization
        ? "结果\n可视化资源已返回，请查看上方入口。"
        : `结果\n${props.message.result}`,
    );
  }
  return details.join("\n\n");
});

const renderedContent = computed(() => renderMarkdown(
  props.message.role === "assistant"
    ? userVisibleAssistantContent(props.message.content)
    : props.message.content,
));
const renderedResult = computed(() => renderMarkdown(props.message.result));
</script>

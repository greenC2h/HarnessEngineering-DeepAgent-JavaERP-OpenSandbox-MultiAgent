/** Enter 仅在非输入法组合且没有修饰键时发送。 */
export function shouldSendOnEnter(event, isComposing = false) {
  return event.key === "Enter" && !event.isComposing && !isComposing && event.keyCode !== 229
    && !event.shiftKey && !event.ctrlKey && !event.altKey && !event.metaKey;
}

/** 只允许普通网页资源，拒绝脚本、内联文档及其他协议。 */
export function safeVisualizationUrl(value) {
  if (typeof value !== "string" || !value.trim()) return "";
  try {
    const url = new URL(value, "https://local.invalid/");
    return ["http:", "https:"].includes(url.protocol) ? value : "";
  } catch { return ""; }
}

/** 图片预览兼容严格 Base64 的位图数据；链接仍仅允许 HTTP(S)。 */
export function safeImageUrl(value) {
  if (typeof value !== "string") return "";
  const match = /^data:image\/(?:png|jpeg|gif|webp);base64,((?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?)$/i.exec(value);
  if (match?.[1]) return value;
  return safeVisualizationUrl(value);
}

export function asyncTaskToolStatus(status) {
  if (!status.done) return "calling";
  return status.status === "success" && !status.error ? "done" : "failed";
}

export function approvalDecisions(actions, type) {
  return { decisions: (actions || []).map(() => ({ type })) };
}

/** 过滤模型泄露的内部执行旁白，保留面向业务的最终结果。 */
export function isInternalAgentNarration(content) {
  if (typeof content !== "string") return false;
  return /(?:\b(?:delegate|delegating|sub-?agent|preferences?\s+file)\b|\b(?:i|we)['’]?ll\s+(?:(?:re)?launch|start|dispatch|run)\b.*\b(?:analysis|task)\b|我将委派|正在委派|读取.*(?:偏好|记忆).*(?:文件|后))/i.test(content);
}

/** 将已持久化的框架限额错误转换为面向用户的任务结果。 */
export function userVisibleAssistantContent(content) {
  if (typeof content !== "string") return content;
  if (/(?:tool call limit reached|model call limits exceeded)/i.test(content)) {
    return "本次分析未能形成完整结论。请重试或缩小分析范围后再获取报告。";
  }
  return content
    .replace(/^[^\r\n]*(?:资源(?:\s|\*|_)*ID|静态(?:\s|\*|_)*HTML(?:\s|\*|_)*文件)[^\r\n]*(?:\r?\n|$)/gim, "")
    .replace(/^\s*(?:主\s*Agent|main\s+agent)\s*[：:,，]?\s*/i, "");
}

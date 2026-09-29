/** 查询后台异步子 Agent 任务。 */

import { responseError } from "./chat.js";

export async function getAsyncTaskStatus(taskId, userId, { signal } = {}) {
  const response = await fetch(`/async-tasks/${encodeURIComponent(taskId)}?user_id=${encodeURIComponent(userId)}`, { signal });
  if (!response.ok) {
    throw await responseError(response);
  }
  return response.json();
}

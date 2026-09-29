async function readError(response) {
  const text = await response.text();
  try {
    const detail = JSON.parse(text).detail;
    return detail || text;
  } catch {
    return text || `请求失败 (${response.status})`;
  }
}

export async function getCaptcha({ signal } = {}) {
  const response = await fetch("/auth/captcha", { signal });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function getCurrentUser({ signal } = {}) {
  const response = await fetch("/auth/me", { signal });
  if (!response.ok) throw new Error(await readError(response));
  return authenticateResponse(await response.json());
}

async function authenticate(path, payload, { signal } = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) throw new Error(await readError(response));
  return authenticateResponse(await response.json());
}

function authenticateResponse(responseBody) {
  // 后端遵循 Python/Pydantic 的 snake_case，应用状态和后续 API 调用统一使用 camelCase。
  // 在接口边界转换可避免认证成功后因 userId 缺失回退为默认演示账户。
  if (typeof responseBody.user_id !== "string" || typeof responseBody.username !== "string") {
    throw new Error("认证响应缺少用户身份");
  }
  return { userId: responseBody.user_id, username: responseBody.username };
}

export function login(payload, options) {
  return authenticate("/auth/login", payload, options);
}

export function register(payload, options) {
  return authenticate("/auth/register", payload, options);
}

export async function logout({ signal } = {}) {
  const response = await fetch("/auth/logout", { method: "POST", signal });
  if (!response.ok) throw new Error(await readError(response));
}

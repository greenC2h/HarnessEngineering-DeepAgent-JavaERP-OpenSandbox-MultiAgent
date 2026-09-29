import test from "node:test";
import assert from "node:assert/strict";

import { login } from "../src/api/auth.js";

test("login normalizes the API identity before it reaches application state", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({
    user_id: "u-e2e",
    username: "E2E采购测试",
  }), { status: 200 }));

  const identity = await login({ username: "E2E采购测试" });
  assert.deepEqual(identity, { userId: "u-e2e", username: "E2E采购测试" });
});

test("login rejects a malformed successful authentication response", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ username: "缺少编号" }), {
    status: 200,
  }));

  await assert.rejects(login({ username: "缺少编号" }), /缺少用户身份/);
});

<template>
  <main class="auth-layout">
    <section class="auth-panel" aria-labelledby="auth-title">
      <div class="auth-mark" aria-hidden="true"><span>ERP</span><span>PROCUREMENT</span></div>
      <p class="eyebrow">ERP PROCUREMENT</p>
      <h1 id="auth-title">采购智能助手</h1>
      <p class="auth-intro">登录后继续处理采购对话，或注册新的账号。</p>

      <div class="auth-tabs" role="tablist" aria-label="账户操作">
        <button type="button" :class="{ active: mode === 'login' }" @click="switchMode('login')">登录</button>
        <button type="button" :class="{ active: mode === 'register' }" @click="switchMode('register')">注册</button>
      </div>

      <form class="auth-form" @submit.prevent="submit">
        <label>
          <span>账号</span>
          <input v-model.trim="account" inputmode="numeric" autocomplete="username" minlength="6" maxlength="20" pattern="[0-9]+" required placeholder="6-20 位数字账号" />
        </label>
        <label>
          <span>密码</span>
          <input v-model="password" type="password" autocomplete="current-password" minlength="8" maxlength="64" required placeholder="8-64 位密码" />
        </label>
        <label v-if="mode === 'register'">
          <span>数字验证码</span>
          <div class="captcha-row">
            <input v-model.trim="captcha" inputmode="numeric" autocomplete="off" maxlength="4" required placeholder="输入图片中的数字" />
            <button class="captcha-image-button" type="button" title="刷新验证码" aria-label="刷新验证码" @click="refreshCaptcha">
              <img v-if="captchaImage" :src="captchaImage" alt="数字验证码，点击刷新" />
              <span v-else>加载中</span>
            </button>
          </div>
        </label>
        <p v-if="errorMessage" class="auth-error" role="alert">{{ errorMessage }}</p>
        <button class="auth-submit" type="submit" :disabled="isSubmitting || (mode === 'register' && !captchaId)">
          {{ isSubmitting ? "处理中..." : mode === "login" ? "进入工作台" : "创建账号" }}
        </button>
      </form>

      <p class="auth-note">账号仅允许数字；注册需要验证码，登录只校验账号和密码。</p>
    </section>
  </main>
</template>

<script setup>
import { ref } from "vue";

import { getCaptcha, login, register } from "../api/auth";

const emit = defineEmits(["authenticated"]);
const mode = ref("login");
const account = ref("");
const password = ref("");
const captcha = ref("");
const captchaId = ref("");
const captchaImage = ref("");
const errorMessage = ref("");
const isSubmitting = ref(false);

async function refreshCaptcha() {
  errorMessage.value = "";
  captcha.value = "";
  try {
    const response = await getCaptcha();
    captchaId.value = response.captcha_id;
    captchaImage.value = response.image;
  } catch (error) {
    errorMessage.value = error.message || "验证码加载失败，请重试";
  }
}

function switchMode(nextMode) {
  mode.value = nextMode;
  errorMessage.value = "";
  captcha.value = "";
  if (nextMode === "register") refreshCaptcha();
}

async function submit() {
  if (isSubmitting.value) return;
  isSubmitting.value = true;
  errorMessage.value = "";
  try {
    const request = { account: account.value, password: password.value };
    if (mode.value === "register") {
      request.captcha_id = captchaId.value;
      request.captcha = captcha.value;
    }
    const response = mode.value === "login" ? await login(request) : await register(request);
    emit("authenticated", response);
  } catch (error) {
    errorMessage.value = error.message || "操作失败，请重试";
    if (mode.value === "register") await refreshCaptcha();
  } finally {
    isSubmitting.value = false;
  }
}

</script>

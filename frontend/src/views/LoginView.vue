<template>
  <div class="login-page">
    <section class="login-card">
      <div class="login-avatar-shell">
        <img class="login-avatar" src="/aniu.ico" alt="Aniu avatar" />
      </div>

      <div class="login-copy">
        <h1>Aniu</h1>
        <p>输入密码登录 AI 模拟交易系统</p>
      </div>

      <form class="login-form" @submit.prevent="handleSubmit">
        <label class="field">
          <span>密码</span>
          <input v-model="password" type="password" placeholder="请输入密码" autocomplete="current-password" />
        </label>

        <label class="login-remember-row">
          <input v-model="rememberCredentials" type="checkbox" />
          <span>默认记住密码</span>
        </label>
        <p class="login-remember-hint">
          记住密码会将密码保存在当前浏览器中。共享设备或存在脚本风险时请勿启用。
        </p>
        <button
          v-if="hasRememberedPassword"
          type="button"
          class="button ghost small login-clear-remembered"
          @click="clearRememberedPassword"
        >
          清除已记住密码
        </button>

        <p v-if="errorMessage" class="login-error">{{ errorMessage }}</p>

        <button class="button primary login-submit" :disabled="submitting" type="submit">登录</button>
      </form>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  api,
  clearStoredLoginFlag,
  clearStoredLoginNotice,
  clearStoredToken,
  consumeStoredLoginNotice,
  consumeStoredLoginRedirect,
  getStoredLoginFlag,
  getStoredToken,
  setStoredLoginFlag,
  setStoredToken,
} from '@/services/api'
import {
  REMEMBERED_PASSWORD_STORAGE_KEY,
} from '@/constants'

const router = useRouter()
const password = ref('')
const rememberCredentials = ref(true)
const hasRememberedPassword = ref(false)
const errorMessage = ref('')
const submitting = ref(false)

function resolvePostLoginPath() {
  return consumeStoredLoginRedirect() || '/overview'
}

onMounted(() => {
  password.value = window.localStorage.getItem(REMEMBERED_PASSWORD_STORAGE_KEY) ?? ''
  hasRememberedPassword.value = password.value.length > 0
  const pendingNotice = consumeStoredLoginNotice()
  if (pendingNotice) {
    errorMessage.value = pendingNotice
  }

  if (getStoredLoginFlag() && getStoredToken()) {
    router.replace(resolvePostLoginPath())
  }
})

function clearRememberedPassword() {
  window.localStorage.removeItem(REMEMBERED_PASSWORD_STORAGE_KEY)
  hasRememberedPassword.value = false
  if (rememberCredentials.value) {
    rememberCredentials.value = false
  }
}

async function handleSubmit() {
  if (!password.value.trim()) {
    errorMessage.value = '请输入密码。'
    return
  }

  submitting.value = true
  try {
    const response = await api.login({
      password: password.value,
    })
    if (!response.authenticated || !response.token) {
      throw new Error('登录失败，请检查密码。')
    }
    setStoredToken(response.token)
    setStoredLoginFlag(response.authenticated)
    if (rememberCredentials.value) {
      window.localStorage.setItem(REMEMBERED_PASSWORD_STORAGE_KEY, password.value)
      hasRememberedPassword.value = true
    } else {
      window.localStorage.removeItem(REMEMBERED_PASSWORD_STORAGE_KEY)
      hasRememberedPassword.value = false
    }
    errorMessage.value = ''
    clearStoredLoginNotice()
    router.replace(resolvePostLoginPath())
  } catch (error) {
    clearStoredToken()
    clearStoredLoginFlag()
    errorMessage.value = (error as Error).message
  } finally {
    submitting.value = false
  }
}
</script>

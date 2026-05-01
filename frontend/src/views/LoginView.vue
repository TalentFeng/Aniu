<template>
  <div class="login-page">
    <section class="login-card">
      <div class="login-avatar-shell">
        <img class="login-avatar" src="/aniu.ico" alt="Aniu avatar" />
      </div>

      <div class="login-copy">
        <h1>Aniu</h1>
        <p>输入用户名和密码登录 AI 模拟交易系统</p>
      </div>

      <form class="login-form" @submit.prevent="handleSubmit">
        <label class="field">
          <span>用户名</span>
          <input v-model="username" type="text" placeholder="请输入用户名" autocomplete="username" />
        </label>

        <label class="field">
          <span>密码</span>
          <input v-model="password" type="password" placeholder="请输入密码" autocomplete="current-password" />
        </label>

        <label class="login-remember-row">
          <input v-model="rememberCredentials" type="checkbox" />
          <span>默认记住密码</span>
        </label>

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
  clearRememberedUsername,
  consumeStoredLoginNotice,
  consumeStoredLoginRedirect,
  getRememberedUsername,
  getStoredLoginFlag,
  getStoredToken,
  setRememberedUsername,
  setStoredCurrentUser,
  setStoredLoginFlag,
  setStoredToken,
} from '@/services/api'
import {
  REMEMBERED_PASSWORD_STORAGE_KEY,
} from '@/constants'

const router = useRouter()
const username = ref('')
const password = ref('')
const rememberCredentials = ref(true)
const errorMessage = ref('')
const submitting = ref(false)

function resolvePostLoginPath() {
  return consumeStoredLoginRedirect() || '/overview'
}

onMounted(() => {
  username.value = getRememberedUsername()
  password.value = window.localStorage.getItem(REMEMBERED_PASSWORD_STORAGE_KEY) ?? ''
  const pendingNotice = consumeStoredLoginNotice()
  if (pendingNotice) {
    errorMessage.value = pendingNotice
  }

  if (getStoredLoginFlag() && getStoredToken()) {
    router.replace(resolvePostLoginPath())
  }
})

async function handleSubmit() {
  if (!username.value.trim()) {
    errorMessage.value = '请输入用户名。'
    return
  }
  if (!password.value.trim()) {
    errorMessage.value = '请输入密码。'
    return
  }

  submitting.value = true
  try {
    const response = await api.login({
      username: username.value.trim(),
      password: password.value,
    })
    if (!response.authenticated || !response.token || !response.user) {
      throw new Error('登录失败，请检查密码。')
    }
    setStoredToken(response.token)
    setStoredCurrentUser(response.user)
    setStoredLoginFlag(response.authenticated)
    if (rememberCredentials.value) {
      setRememberedUsername(username.value.trim())
      window.localStorage.setItem(REMEMBERED_PASSWORD_STORAGE_KEY, password.value)
    } else {
      clearRememberedUsername()
      window.localStorage.removeItem(REMEMBERED_PASSWORD_STORAGE_KEY)
    }
    errorMessage.value = ''
    clearStoredLoginNotice()
    router.replace(resolvePostLoginPath())
  } catch (error) {
    clearStoredToken()
    clearStoredLoginFlag()
    setStoredCurrentUser(null)
    errorMessage.value = (error as Error).message
  } finally {
    submitting.value = false
  }
}
</script>

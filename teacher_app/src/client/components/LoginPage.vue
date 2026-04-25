<template>
  <div class="login-page">
    <!-- 左上角 logo -->
    <div class="login-top-logo">
      <img :src="BASE + 'header-logo.webp'" alt="Logo">
    </div>

    <!-- 中间登录卡片 -->
    <div class="login-card">
      <h1 class="login-title">教师备课助手</h1>
      <p class="login-subtitle">AI 生成交互式数学图示，助力高效备课</p>

      <div class="login-tabs">
        <button :class="{ active: mode === 'login' }" @click="mode = 'login'">登录</button>
        <button :class="{ active: mode === 'register' }" @click="mode = 'register'">注册</button>
      </div>

      <form @submit.prevent="submit" class="login-form">
        <div class="login-field">
          <label>用户名</label>
          <input v-model="username" type="text" placeholder="请输入用户名" autocomplete="username" required>
        </div>
        <div class="login-field">
          <label>密码</label>
          <input v-model="password" type="password" placeholder="请输入密码" autocomplete="current-password" required>
        </div>
        <p v-if="error" class="login-error">{{ error }}</p>
        <button type="submit" class="btn btn-primary login-submit" :disabled="loading">
          {{ loading ? '请稍候…' : (mode === 'login' ? '登录' : '注册') }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { login, register } from '../composables/useAuth'

const BASE = import.meta.env.BASE_URL

const emit = defineEmits<{ success: [] }>()

const mode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  loading.value = true
  try {
    if (mode.value === 'login') {
      await login(username.value, password.value)
    } else {
      await register(username.value, password.value)
    }
    emit('success')
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

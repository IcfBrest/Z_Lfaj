<script setup>
import { ref } from 'vue'
import { api } from '../api.js'

const mode = ref('login')
const username = ref('')
const password = ref('')
const email = ref('')
const invitationCode = ref('')
const error = ref('')

async function submit() {
  error.value = ''
  try {
    const body =
      mode.value === 'login'
        ? { username: username.value, password: password.value }
        : {
            username: username.value,
            password: password.value,
            email: email.value || null,
            invitation_code: invitationCode.value,
          }
    const data = await api.post(`/auth/${mode.value === 'login' ? 'login' : 'register'}`, body)
    localStorage.setItem('token', data.token)
    localStorage.setItem('is_admin', String(data.is_admin))
    location.href = '/'
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="card">
    <h3>{{ mode === 'login' ? '登录' : '注册（凭邀请码）' }}</h3>
    <label>用户名</label>
    <input v-model="username" />
    <label>密码</label>
    <input v-model="password" type="password" />
    <template v-if="mode === 'register'">
      <label>邮箱（可选）</label>
      <input v-model="email" type="email" />
      <label>邀请码</label>
      <input v-model="invitationCode" placeholder="向管理员索取" />
    </template>
    <div class="row" style="margin-top: 16px">
      <button @click="submit">{{ mode === 'login' ? '登录' : '注册' }}</button>
      <button class="secondary" @click="mode = mode === 'login' ? 'register' : 'login'">
        {{ mode === 'login' ? '去注册' : '去登录' }}
      </button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
  </div>
</template>

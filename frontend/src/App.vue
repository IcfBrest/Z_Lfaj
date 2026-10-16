<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const isLogin = computed(() => route.path === '/login')
const isAdmin = computed(() => localStorage.getItem('is_admin') === 'true')

function logout() {
  localStorage.clear()
  router.push('/login')
}
</script>

<template>
  <div v-if="isLogin" class="main" style="max-width: 420px; margin: 8vh auto">
    <router-view />
  </div>
  <div v-else class="layout">
    <nav class="sidebar">
      <h2>AI 求职助手</h2>
      <router-link to="/">岗位</router-link>
      <router-link to="/resumes">简历</router-link>
      <router-link to="/settings">设置</router-link>
      <router-link v-if="isAdmin" to="/admin">管理</router-link>
      <a href="#" @click.prevent="logout">退出登录</a>
    </nav>
    <main class="main">
      <router-view />
    </main>
  </div>
</template>

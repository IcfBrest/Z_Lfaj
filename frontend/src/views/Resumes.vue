<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const resumes = ref([])
const detail = ref(null)
const message = ref('')
const fileInput = ref(null)

async function refresh() {
  resumes.value = await api.get('/resumes')
}

async function upload() {
  const file = fileInput.value?.files?.[0]
  if (!file) return
  message.value = '上传并解析中…'
  const form = new FormData()
  form.append('file', file)
  try {
    const resp = await api.upload('/resumes', form)
    message.value = `已上传（版本 v${resp.version}${resp.is_master ? '，master' : ''}），解析中…`
    await poll(resp.task_id)
  } catch (e) {
    message.value = e.message
  }
}

async function poll(taskId) {
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 1500))
    const t = await api.get(`/tasks/${taskId}`)
    if (t.status === 'done') {
      message.value = '解析完成'
      await refresh()
      return
    }
    if (t.status === 'failed') {
      message.value = `解析失败：${t.error}`
      await refresh()
      return
    }
  }
  message.value = '解析超时，稍后在列表中查看状态'
}

async function view(r) {
  detail.value = await api.get(`/resumes/${r.id}`)
}

async function setMaster(r) {
  await api.post(`/resumes/${r.id}/set-master`)
  await refresh()
}

async function remove(r) {
  if (!confirm(`删除简历「${r.name}」及其关联数据？`)) return
  await api.del(`/resumes/${r.id}`)
  detail.value = null
  await refresh()
}

onMounted(refresh)
</script>

<template>
  <div class="card">
    <h3>上传简历（PDF / DOCX / MD）</h3>
    <div class="row">
      <input ref="fileInput" type="file" accept=".pdf,.docx,.md" style="width: auto" />
      <button @click="upload">上传并解析</button>
      <span class="muted">{{ message }}</span>
    </div>
    <p class="muted" style="margin-top: 8px">
      解析默认开启脱敏：姓名/手机号/邮箱在发送给大模型前会被占位符替换，原文加密存储于平台。
    </p>
  </div>

  <div class="card">
    <h3>我的简历</h3>
    <table>
      <thead><tr><th>名称</th><th>版本</th><th>状态</th><th>master</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="r in resumes" :key="r.id">
          <td>{{ r.name }}</td>
          <td>v{{ r.version }}</td>
          <td>
            <span class="tag" :class="r.parse_status === 'done' ? 'green' : r.parse_status === 'failed' ? 'red' : 'gray'">
              {{ r.parse_status }}
            </span>
            <div v-if="r.parse_error" class="muted">{{ r.parse_error }}</div>
          </td>
          <td><span v-if="r.is_master" class="tag green">master</span></td>
          <td class="row">
            <button class="secondary" @click="view(r)">查看</button>
            <button v-if="!r.is_master" class="secondary" @click="setMaster(r)">设为 master</button>
            <button class="danger" @click="remove(r)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div v-if="detail" class="card">
    <h3>{{ detail.name }}（v{{ detail.version }}）</h3>
    <pre style="white-space: pre-wrap; font-size: 12px; max-height: 480px; overflow: auto">{{ JSON.stringify(detail.parsed_profile, null, 2) }}</pre>
  </div>
</template>

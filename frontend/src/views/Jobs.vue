<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'

const tab = ref('shared')
const companies = ref([])
const sharedJobs = ref([])
const myJobs = ref([])
const jdText = ref('')
const companyName = ref('')
const selectedCompany = ref(null)
const isAdmin = localStorage.getItem('is_admin') === 'true'
const lastTask = ref(null)
const message = ref('')
let timer = null

async function refresh() {
  companies.value = await api.get('/companies')
  sharedJobs.value = await api.get('/jobs/shared')
  myJobs.value = await api.get('/jobs/mine')
}

async function pollTask() {
  if (!lastTask.value) return
  try {
    const t = await api.get(`/tasks/${lastTask.value}`)
    if (t.status === 'done') {
      message.value = '解析完成'
      lastTask.value = null
      clearInterval(timer)
      await refresh()
    } else if (t.status === 'failed') {
      message.value = `解析失败：${t.error}`
      lastTask.value = null
      clearInterval(timer)
    }
  } catch {
    /* 轮询失败静默，下轮重试 */
  }
}

async function importJd() {
  message.value = ''
  const body = { jd_text: jdText.value, company_name: companyName.value || null }
  if (isAdmin && selectedCompany.value) body.company_id = selectedCompany.value
  try {
    const resp = await api.post('/jobs/manual', body)
    lastTask.value = resp.task_id
    message.value = '已提交解析…'
    clearInterval(timer)
    timer = setInterval(pollTask, 1000)
  } catch (e) {
    message.value = e.message
  }
}

onMounted(async () => {
  await refresh()
  timer = setInterval(pollTask, 2000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="card">
    <h3>粘贴 JD 导入</h3>
    <div class="row" v-if="isAdmin">
      <select v-model="selectedCompany" style="width: 220px">
        <option :value="null">— 不入库共享库（作为我的私有岗位）—</option>
        <option v-for="c in companies" :key="c.id" :value="c.id">{{ c.name }}（共享库）</option>
      </select>
    </div>
    <label v-else>公司名</label>
    <input v-if="!isAdmin" v-model="companyName" placeholder="例如：某创业公司" />
    <label>JD 原文</label>
    <textarea v-model="jdText" placeholder="粘贴岗位描述全文…"></textarea>
    <div class="row" style="margin-top: 12px">
      <button :disabled="jdText.length < 20" @click="importJd">提交解析</button>
      <span class="muted">{{ message }}</span>
    </div>
  </div>

  <div class="card">
    <div class="row" style="margin-bottom: 12px">
      <button :class="tab === 'shared' ? '' : 'secondary'" @click="tab = 'shared'">共享岗位库</button>
      <button :class="tab === 'mine' ? '' : 'secondary'" @click="tab = 'mine'">我的私有岗位</button>
    </div>
    <table>
      <thead>
        <tr>
          <th>公司</th><th>岗位</th><th>城市</th><th>经验</th><th>技能</th><th>来源</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="j in tab === 'shared' ? sharedJobs : myJobs" :key="j.id">
          <td>{{ j.company }}</td>
          <td>{{ j.title }}</td>
          <td>{{ j.location || '—' }}</td>
          <td>{{ j.experience_required || '—' }}</td>
          <td>
            <span v-for="s in (j.skills || []).slice(0, 5)" :key="s" class="tag">{{ s }}</span>
          </td>
          <td><span class="tag gray">{{ j.source_type }}</span></td>
        </tr>
        <tr v-if="(tab === 'shared' ? sharedJobs : myJobs).length === 0">
          <td colspan="6" class="muted">暂无岗位，先粘贴导入一个</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

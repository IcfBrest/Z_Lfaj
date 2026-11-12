<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const users = ref([])
const invitations = ref([])
const companyName = ref('')
const careerUrl = ref('')
const companies = ref([])
const sources = ref([])
const scrapes = ref({})
const scrapeLimit = ref('')
const listOnly = ref(false)
const message = ref('')

async function refresh() {
  users.value = await api.get('/admin/users')
  invitations.value = await api.get('/admin/invitations')
  companies.value = await api.get('/companies')
  sources.value = await api.get('/admin/scrape/sources')
}

async function genInvite() {
  const r = await api.post('/admin/invitations')
  message.value = `新邀请码：${r.code}（复制发给朋友）`
  await refresh()
}

async function revoke(code) {
  try {
    await api.post(`/admin/invitations/${code}/revoke`)
  } catch (e) {
    message.value = e.message
  }
  await refresh()
}

async function toggle(u) {
  await api.post(`/admin/users/${u.id}/${u.is_disabled ? 'enable' : 'disable'}`)
  await refresh()
}

async function resetPwd(u) {
  const pwd = prompt(`为 ${u.username} 设置新密码（至少8位）`)
  if (!pwd) return
  try {
    await api.post(`/admin/users/${u.id}/reset-password`, { new_password: pwd })
    message.value = '已重置'
  } catch (e) {
    message.value = e.message
  }
}

async function addCompany() {
  try {
    await api.post('/companies', { name: companyName.value, career_url: careerUrl.value || null })
    companyName.value = careerUrl.value = ''
    await refresh()
  } catch (e) {
    message.value = e.message
  }
}

function fmtTime(value) {
  return value ? new Date(value).toLocaleString() : '从未同步'
}

function setScrape(source, status, text) {
  scrapes.value = { ...scrapes.value, [source]: { status, text } }
}

async function syncSource(source) {
  const body = { source, fetch_detail: !listOnly.value }
  const limit = parseInt(scrapeLimit.value, 10)
  if (limit > 0) body.limit = limit
  try {
    const r = await api.post('/admin/scrape', body)
    setScrape(source, 'running', '同步中…')
    pollScrape(source, r.task_id)
  } catch (e) {
    setScrape(source, 'failed', e.message)
  }
}

function pollScrape(source, taskId) {
  const timer = setInterval(async () => {
    let task
    try {
      task = await api.get(`/tasks/${taskId}`)
    } catch (e) {
      clearInterval(timer)
      setScrape(source, 'failed', e.message)
      return
    }
    if (task.status === 'done') {
      clearInterval(timer)
      const r = task.result || {}
      setScrape(
        source,
        'done',
        `新增 ${r.created}、更新 ${r.updated}、未变 ${r.unchanged}、下架 ${r.deactivated}、失败 ${r.failed}｜站点共 ${r.total} 条`,
      )
      await refresh()
    } else if (task.status === 'failed') {
      clearInterval(timer)
      setScrape(source, 'failed', task.error || '同步失败')
    }
  }, 1500)
}

onMounted(refresh)
</script>

<template>
  <div class="card">
    <h3>邀请码</h3>
    <div class="row">
      <button @click="genInvite">生成邀请码</button>
      <span class="muted">{{ message }}</span>
    </div>
    <table>
      <thead><tr><th>码</th><th>状态</th><th>使用者</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="i in invitations" :key="i.code">
          <td><code>{{ i.code }}</code></td>
          <td>
            <span class="tag" :class="i.used_by ? 'gray' : i.is_revoked ? 'red' : 'green'">
              {{ i.used_by ? '已使用' : i.is_revoked ? '已作废' : '可用' }}
            </span>
          </td>
          <td>{{ i.used_by || '—' }}</td>
          <td>
            <button v-if="!i.used_by && !i.is_revoked" class="danger" @click="revoke(i.code)">作废</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="card">
    <h3>公司（共享岗位库归属）</h3>
    <div class="row">
      <input v-model="companyName" placeholder="公司名，如 米哈游" style="width: 200px" />
      <input v-model="careerUrl" placeholder="招聘官网 URL（Phase 3+ 采集用，可选）" style="flex: 1" />
      <button @click="addCompany">添加</button>
    </div>
    <table>
      <thead><tr><th>公司</th><th>官网</th></tr></thead>
      <tbody>
        <tr v-for="c in companies" :key="c.id"><td>{{ c.name }}</td><td class="muted">{{ c.career_url || '—' }}</td></tr>
      </tbody>
    </table>
  </div>

  <div class="card">
    <h3>站点采集</h3>
    <div class="row">
      <input v-model="scrapeLimit" placeholder="每站最多抓几条（留空 = 全量）" style="width: 240px" />
      <label class="muted">
        <input v-model="listOnly" type="checkbox" />
        只抓列表，不抓详情
      </label>
    </div>
    <p class="muted">采集是后台任务：先抓列表、再逐条抓详情，按外部 id 去重；整轮跑完后才把站点上已消失的岗位标为下架。</p>
    <table>
      <thead><tr><th>站点</th><th>在架 / 累计</th><th>最近同步</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="s in sources" :key="s.source">
          <td>
            <strong>{{ s.company }}</strong>
            <div class="muted">{{ s.source }}</div>
          </td>
          <td>{{ s.active_jobs }} / {{ s.total_jobs }}</td>
          <td class="muted">{{ fmtTime(s.last_scraped_at) }}</td>
          <td>
            <button
              :disabled="scrapes[s.source] && scrapes[s.source].status === 'running'"
              @click="syncSource(s.source)"
            >
              {{ scrapes[s.source] && scrapes[s.source].status === 'running' ? '同步中…' : '同步' }}
            </button>
            <div v-if="scrapes[s.source]" class="muted" :class="{ error: scrapes[s.source].status === 'failed' }">
              {{ scrapes[s.source].text }}
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="card">
    <h3>用户</h3>
    <table>
      <thead><tr><th>ID</th><th>用户名</th><th>角色</th><th>状态</th><th>邀请码</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="u in users" :key="u.id">
          <td>{{ u.id }}</td>
          <td>{{ u.username }}</td>
          <td>{{ u.is_admin ? '管理员' : '用户' }}</td>
          <td>
            <span class="tag" :class="u.is_disabled ? 'red' : 'green'">{{ u.is_disabled ? '禁用' : '正常' }}</span>
          </td>
          <td class="muted">{{ u.invited_by_code || '—' }}</td>
          <td class="row">
            <button v-if="u.username !== 'admin'" class="secondary" @click="toggle(u)">
              {{ u.is_disabled ? '启用' : '禁用' }}
            </button>
            <button class="secondary" @click="resetPwd(u)">重置密码</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

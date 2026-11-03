<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'

const tab = ref('shared')
const companies = ref([])
const sharedJobs = ref([])
const myJobs = ref([])
const jdText = ref('')
const companyName = ref('')
const selectedCompany = ref(null)
const isAdmin = localStorage.getItem('is_admin') === 'true'
const sortByScore = ref(false)
const parseTask = ref(null)
const scoreTask = ref(null)
const parseMessage = ref('')
const scoreMessage = ref('')
const detail = ref(null)
const detailLoading = ref(false)
let timer = null

const jobs = computed(() => (tab.value === 'shared' ? sharedJobs.value : myJobs.value))

function scoreClass(score) {
  if (score === null || score === undefined) return 'gray'
  if (score >= 75) return 'green'
  if (score >= 60) return ''
  return 'red'
}

async function refresh() {
  const suffix = sortByScore.value ? '?sort=score' : ''
  companies.value = await api.get('/companies')
  sharedJobs.value = await api.get(`/jobs/shared${suffix}`)
  myJobs.value = await api.get(`/jobs/mine${suffix}`)
}

async function poll() {
  if (parseTask.value) {
    try {
      const t = await api.get(`/tasks/${parseTask.value}`)
      if (t.status === 'done') {
        parseMessage.value = '解析完成'
        parseTask.value = null
        await refresh()
      } else if (t.status === 'failed') {
        parseMessage.value = `解析失败：${t.error}`
        parseTask.value = null
      }
    } catch {
      /* 下轮重试 */
    }
  }
  if (scoreTask.value) {
    try {
      const t = await api.get(`/tasks/${scoreTask.value}`)
      if (t.status === 'done') {
        const r = t.result || {}
        scoreMessage.value =
          `已打分 ${r.scored || 0} 个｜缓存 ${r.cached || 0} 个｜` +
          `硬规则排除 ${(r.excluded || []).length} 个` +
          (r.failed ? `｜失败 ${r.failed} 个` : '')
        scoreTask.value = null
        await refresh()
      } else if (t.status === 'failed') {
        scoreMessage.value = `打分失败：${t.error}`
        scoreTask.value = null
      }
    } catch {
      /* 下轮重试 */
    }
  }
}

async function importJd() {
  parseMessage.value = ''
  const body = { jd_text: jdText.value, company_name: companyName.value || null }
  if (isAdmin && selectedCompany.value) body.company_id = selectedCompany.value
  try {
    const resp = await api.post('/jobs/manual', body)
    parseTask.value = resp.task_id
    parseMessage.value = '已提交解析…'
  } catch (e) {
    parseMessage.value = e.message
  }
}

async function scoreAll() {
  scoreMessage.value = ''
  try {
    const resp = await api.post('/matches/run', { force: false })
    scoreTask.value = resp.task_id
    scoreMessage.value = `开始打分（最多 ${resp.limit} 个岗位）…`
  } catch (e) {
    scoreMessage.value = e.message
  }
}

async function scoreOne(job) {
  scoreMessage.value = ''
  const refType = tab.value === 'shared' ? 'job_posting' : 'user_manual_job'
  try {
    const resp = await api.post(`/matches/jobs/${refType}/${job.id}`, { force: false })
    scoreTask.value = resp.task_id
    scoreMessage.value = `正在给「${job.title}」打分…`
  } catch (e) {
    scoreMessage.value = e.message
  }
}

async function openDetail(job) {
  if (!job.match_id) return
  detailLoading.value = true
  try {
    detail.value = await api.get(`/matches/${job.match_id}`)
  } catch (e) {
    scoreMessage.value = e.message
  } finally {
    detailLoading.value = false
  }
}

async function toggleSort() {
  sortByScore.value = !sortByScore.value
  await refresh()
}

onMounted(async () => {
  await refresh()
  timer = setInterval(poll, 1500)
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
      <span class="muted">{{ parseMessage }}</span>
    </div>
  </div>

  <div class="card">
    <div class="row" style="margin-bottom: 12px">
      <button :class="tab === 'shared' ? '' : 'secondary'" @click="tab = 'shared'">共享岗位库</button>
      <button :class="tab === 'mine' ? '' : 'secondary'" @click="tab = 'mine'">我的私有岗位</button>
      <button class="secondary" @click="toggleSort">
        {{ sortByScore ? '恢复默认排序' : '按匹配分排序' }}
      </button>
      <button :disabled="scoreTask !== null" @click="scoreAll">
        {{ scoreTask ? '打分中…' : '给当前简历批量打分' }}
      </button>
      <span class="muted">{{ scoreMessage }}</span>
    </div>
    <table>
      <thead>
        <tr>
          <th>公司</th><th>岗位</th><th>城市</th><th>经验</th><th>匹配分</th><th>技能</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="j in jobs" :key="j.id">
          <td>{{ j.company }}</td>
          <td>{{ j.title }}</td>
          <td>{{ j.location || '—' }}</td>
          <td>{{ j.experience_required || '—' }}</td>
          <td>
            <span v-if="j.match_score !== null && j.match_score !== undefined" :class="['tag', scoreClass(j.match_score)]">
              {{ j.match_score }}
            </span>
            <span v-else class="muted">未打分</span>
          </td>
          <td>
            <span v-for="s in (j.skills || []).slice(0, 5)" :key="s" class="tag">{{ s }}</span>
          </td>
          <td class="row">
            <button class="secondary" :disabled="scoreTask !== null" @click="scoreOne(j)">打分</button>
            <button v-if="j.match_id" class="secondary" @click="openDetail(j)">详情</button>
          </td>
        </tr>
        <tr v-if="jobs.length === 0">
          <td colspan="7" class="muted">暂无岗位，先粘贴导入一个</td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="card" v-if="detailLoading || detail">
    <div class="row" style="margin-bottom: 8px">
      <h3 style="margin: 0">匹配详情</h3>
      <button class="secondary" @click="detail = null">关闭</button>
    </div>
    <template v-if="detail">
      <div class="row" style="margin-bottom: 8px">
        <strong>{{ detail.title }}</strong>
        <span class="muted">{{ detail.company }}｜{{ detail.location || '城市未知' }}</span>
        <span :class="['tag', scoreClass(detail.score)]">总分 {{ detail.score }}</span>
        <span class="tag gray">{{ detail.verdict || '—' }}</span>
      </div>
      <table style="margin-bottom: 12px">
        <thead>
          <tr><th>维度</th><th>得分</th><th>权重</th></tr>
        </thead>
        <tbody>
          <tr v-for="(value, name) in detail.dimension_scores" :key="name">
            <td>{{ name }}</td>
            <td>{{ value }}</td>
            <td class="muted">{{ (detail.weights || {})[name] ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="detail.reasons">{{ detail.reasons }}</p>
      <div v-if="(detail.matching_points || []).length">
        <label>匹配点</label>
        <ul>
          <li v-for="point in detail.matching_points" :key="point">{{ point }}</li>
        </ul>
      </div>
      <div v-if="(detail.gaps || []).length">
        <label>缺口</label>
        <ul>
          <li v-for="gap in detail.gaps" :key="gap">{{ gap }}</li>
        </ul>
      </div>
      <p class="muted" v-if="detail.score_basis">打分依据：{{ detail.score_basis }}</p>
      <p class="muted" v-if="(detail.missing_dimensions || []).length">
        模型未给出的维度：{{ detail.missing_dimensions.join('、') }}（按 0 分计）
      </p>
    </template>
    <p v-else class="muted">加载中…</p>
  </div>
</template>

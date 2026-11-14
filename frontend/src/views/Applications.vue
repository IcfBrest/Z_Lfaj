<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const STATUS_LABELS = {
  applied: '已投递',
  written_test: '笔试',
  interview: '面试',
  offer: 'Offer',
  rejected: '已拒',
  withdrawn: '已放弃',
}

const items = ref([])
const stats = ref({ total: 0, by_status: {}, stale: 0, active: 0 })
const filter = ref('')
const sort = ref('recent')
const expandedId = ref(null)
const detail = ref(null)
const noteDraft = ref('')
const message = ref('')
const busy = ref(false)

const chips = computed(() => {
  const rows = [{ key: '', label: '全部', count: stats.value.total }]
  Object.keys(STATUS_LABELS).forEach((key) => {
    rows.push({ key, label: STATUS_LABELS[key], count: stats.value.by_status?.[key] || 0 })
  })
  return rows
})

const targetOptions = computed(() => {
  if (!detail.value) return []
  return ['applied', 'written_test', 'interview', 'offer', 'rejected', 'withdrawn'].filter(
    (s) => s !== detail.value.status,
  )
})

function statusClass(status) {
  return `app-status status-${status}`
}

function fmtDate(value) {
  if (!value) return ''
  return new Date(value).toLocaleDateString()
}

async function load() {
  const query = []
  if (filter.value) query.push(`status=${filter.value}`)
  if (sort.value === 'stale') query.push('sort=stale')
  const suffix = query.length ? `?${query.join('&')}` : ''
  const [rows, summary] = await Promise.all([
    api.get(`/applications${suffix}`),
    api.get('/applications/stats'),
  ])
  items.value = rows
  stats.value = summary
}

async function toggle(row) {
  if (expandedId.value === row.id) {
    expandedId.value = null
    detail.value = null
    return
  }
  expandedId.value = row.id
  detail.value = await api.get(`/applications/${row.id}`)
  noteDraft.value = detail.value.note || ''
}

async function move(row, status) {
  if (!status || busy.value) return
  busy.value = true
  try {
    await api.patch(`/applications/${row.id}`, { status })
    message.value = `已推进到「${STATUS_LABELS[status]}」`
    await load()
    if (expandedId.value === row.id) {
      detail.value = await api.get(`/applications/${row.id}`)
    }
  } catch (err) {
    message.value = `推进失败：${err.message}`
  } finally {
    busy.value = false
  }
}

async function saveNote(row) {
  if (busy.value) return
  busy.value = true
  try {
    await api.patch(`/applications/${row.id}`, { note: noteDraft.value })
    message.value = '备注已保存'
    await load()
    detail.value = await api.get(`/applications/${row.id}`)
  } catch (err) {
    message.value = `保存失败：${err.message}`
  } finally {
    busy.value = false
  }
}

function setFilter(key) {
  filter.value = key
  load()
}

function setSort(value) {
  sort.value = value
  load()
}

onMounted(load)
</script>

<template>
  <section>
    <div class="row" style="justify-content: space-between; align-items: baseline">
      <h1>投递记录</h1>
      <p class="muted">
        共 {{ stats.total }} 条 · 进行中 {{ stats.active }} 条 · 停滞 {{ stats.stale }} 条
      </p>
    </div>

    <p class="muted">
      从岗位库点「标记为已投递」即可生成记录。阶段按「已投递 → 笔试 → 面试 → Offer」推进，也可以直接标为已拒/已放弃；
      超过 7 天没更新会标出「N 天无动静」。
    </p>

    <div class="app-chips">
      <button
        v-for="chip in chips"
        :key="chip.key || 'all'"
        class="chip"
        :class="{ active: filter === chip.key }"
        @click="setFilter(chip.key)"
      >
        {{ chip.label }} <span class="chip-count">{{ chip.count }}</span>
      </button>
    </div>

    <div class="row" style="gap: 8px; margin: 10px 0">
      <span class="muted">排序：</span>
      <button class="link" :class="{ active: sort === 'recent' }" @click="setSort('recent')">最近活动</button>
      <button class="link" :class="{ active: sort === 'stale' }" @click="setSort('stale')">最久未更新</button>
    </div>

    <p v-if="message" class="muted">{{ message }}</p>
    <p v-if="!items.length" class="muted">还没有投递记录。</p>

    <article v-for="row in items" :key="row.id" class="card app-card">
      <div class="row" style="justify-content: space-between; align-items: flex-start">
        <div>
          <h3 style="margin: 0">
            {{ row.title }}
            <span :class="statusClass(row.status)">{{ row.status_label }}</span>
            <span v-if="row.is_stale" class="app-stale">⚠ {{ row.days_since_update }} 天无动静</span>
          </h3>
          <p class="muted" style="margin: 4px 0">
            {{ row.company_name }}
            <template v-if="row.location"> · {{ row.location }}</template>
            <template v-if="row.match_score !== null && row.match_score !== undefined">
              · 匹配分 {{ row.match_score }}
            </template>
            · 投递于 {{ fmtDate(row.applied_at) }}
            · 最近活动 {{ row.days_since_update }} 天前
          </p>
          <p v-if="row.note" class="muted">备注：{{ row.note }}</p>
        </div>
        <div class="row" style="gap: 6px; flex-wrap: wrap; justify-content: flex-end">
          <a v-if="row.source_url" :href="row.source_url" target="_blank" rel="noreferrer" class="link">原岗位</a>
          <button class="secondary" @click="toggle(row)">{{ expandedId === row.id ? '收起' : '详情' }}</button>
          <button v-if="row.next_status" :disabled="busy" @click="move(row, row.next_status)">
            {{ row.next_status === 'written_test' ? '标记笔试' : row.next_status === 'interview' ? '标记面试' : '收到 Offer' }}
          </button>
        </div>
      </div>

      <div v-if="expandedId === row.id && detail" class="app-detail">
        <div class="row" style="gap: 8px; flex-wrap: wrap">
          <select :value="''" @change="move(row, $event.target.value); $event.target.value = ''">
            <option value="">推进到…</option>
            <option v-for="option in targetOptions" :key="option" :value="option">
              {{ STATUS_LABELS[option] }}
            </option>
          </select>
          <button
            v-if="row.status !== 'rejected' && row.status !== 'withdrawn'"
            class="secondary"
            :disabled="busy"
            @click="move(row, 'withdrawn')"
          >
            放弃这次投递
          </button>
        </div>

        <div class="row" style="gap: 8px; margin-top: 8px">
          <input v-model="noteDraft" placeholder="记一笔：内推人、面试反馈、下一步…" style="flex: 1" />
          <button class="secondary" :disabled="busy" @click="saveNote(row)">保存备注</button>
        </div>

        <ol class="app-timeline">
          <li v-for="event in detail.events" :key="event.id">
            <strong>{{ event.to_label }}</strong>
            <span class="muted">
              {{ fmtDate(event.created_at) }}
              <template v-if="event.from_status">
                （{{ STATUS_LABELS[event.from_status] }} → {{ STATUS_LABELS[event.to_status] }}）
              </template>
            </span>
            <div v-if="event.note" class="muted">{{ event.note }}</div>
          </li>
        </ol>
      </div>
    </article>
  </section>
</template>

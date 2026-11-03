<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const providers = ref([])
const costs = ref([])
const form = ref({ name: '', base_url: '', api_key: '', default_model: '', task_models: {} })
const message = ref('')
const editingId = ref(null)
const weights = ref({})
const dimensions = ref([])
const weightMessage = ref('')
const rescoring = ref(false)

const PRESETS = [
  { name: 'deepseek', base_url: 'https://api.deepseek.com/v1', default_model: 'deepseek-chat' },
  { name: 'moonshot', base_url: 'https://api.moonshot.cn/v1', default_model: 'kimi-k2-0905-preview' },
  { name: 'zhipu', base_url: 'https://open.bigmodel.cn/api/paas/v4', default_model: 'glm-4.6' },
  { name: 'dashscope', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', default_model: 'qwen-max' },
]

async function refresh() {
  providers.value = await api.get('/providers')
  costs.value = await api.get('/costs/summary')
  const current = await api.get('/matches/weights/current')
  dimensions.value = current.dimensions
  weights.value = { ...current.weights }
}

async function saveWeights() {
  weightMessage.value = ''
  const total = dimensions.value.reduce((sum, d) => sum + Number(weights.value[d] || 0), 0)
  if (total <= 0) {
    weightMessage.value = '四维权重不能全为 0'
    return
  }
  const body = {}
  for (const d of dimensions.value) body[d] = Number(weights.value[d] || 0)
  try {
    const saved = await api.put('/matches/weights', body)
    weights.value = { ...saved.weights }
    weightMessage.value = '已保存（新旧分数需要重算才会更新）'
  } catch (e) {
    weightMessage.value = e.message
  }
}

async function rescore() {
  if (rescoring.value) return
  rescoring.value = true
  weightMessage.value = '已提交重算…'
  try {
    const resp = await api.post('/matches/run', { force: true })
    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, 1500))
      const task = await api.get(`/tasks/${resp.task_id}`)
      if (task.status === 'done') {
        const result = task.result || {}
        weightMessage.value = `重算完成：更新 ${result.scored || 0} 个，缓存 ${result.cached || 0} 个`
        break
      }
      if (task.status === 'failed') {
        weightMessage.value = `重算失败：${task.error}`
        break
      }
    }
  } catch (e) {
    weightMessage.value = e.message
  } finally {
    rescoring.value = false
  }
}

function applyPreset(p) {
  form.value = { ...form.value, name: p.name, base_url: p.base_url, default_model: p.default_model }
}

async function save() {
  message.value = ''
  try {
    if (editingId.value) {
      await api.put(`/providers/${editingId.value}`, form.value)
    } else {
      await api.post('/providers', form.value)
    }
    form.value = { name: '', base_url: '', api_key: '', default_model: '', task_models: {} }
    editingId.value = null
    await refresh()
    message.value = '已保存'
  } catch (e) {
    message.value = e.message
  }
}

function edit(p) {
  editingId.value = p.id
  form.value = {
    name: p.name,
    base_url: p.base_url,
    api_key: p.api_key_masked, // 传回掩码则不覆盖
    default_model: p.default_model || '',
    task_models: p.task_models,
  }
}

async function remove(id) {
  if (!confirm('删除该 provider？')) return
  await api.del(`/providers/${id}`)
  await refresh()
}

async function test(id) {
  message.value = '测试中…'
  const r = await api.post(`/providers/${id}/test`)
  message.value = r.ok ? `连通正常（${r.latency_ms}ms）` : `失败：${r.error}`
}

onMounted(refresh)
</script>

<template>
  <div class="card">
    <h3>{{ editingId ? '编辑' : '添加' }}模型 Provider（自带 API Key）</h3>
    <div class="row" style="margin-bottom: 8px">
      <span class="muted">快速填充：</span>
      <button v-for="p in PRESETS" :key="p.name" class="secondary" @click="applyPreset(p)">{{ p.name }}</button>
    </div>
    <label>名称</label>
    <input v-model="form.name" placeholder="deepseek" />
    <label>Base URL（OpenAI 兼容）</label>
    <input v-model="form.base_url" placeholder="https://api.deepseek.com/v1" />
    <label>API Key（保存后仅显示掩码）</label>
    <input v-model="form.api_key" placeholder="sk-…" />
    <label>默认模型</label>
    <input v-model="form.default_model" placeholder="deepseek-chat" />
    <label>按任务覆盖模型（可选：parse / score / suggest）</label>
    <input v-model="form.task_models.parse" placeholder="解析用模型，留空用默认" style="margin-bottom: 4px" />
    <input v-model="form.task_models.score" placeholder="打分用模型（Phase 1 生效）" style="margin-bottom: 4px" />
    <input v-model="form.task_models.suggest" placeholder="建议用模型（Phase 2 生效）" />
    <div class="row" style="margin-top: 12px">
      <button @click="save">{{ editingId ? '保存修改' : '添加' }}</button>
      <button v-if="editingId" class="secondary" @click="editingId = null; form = { name: '', base_url: '', api_key: '', default_model: '', task_models: {} }">取消编辑</button>
      <span class="muted">{{ message }}</span>
    </div>
  </div>

  <div class="card">
    <h3>我的 Provider</h3>
    <table>
      <thead><tr><th>名称</th><th>Base URL</th><th>Key</th><th>默认模型</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="p in providers" :key="p.id">
          <td>{{ p.name }}</td>
          <td class="muted">{{ p.base_url }}</td>
          <td><code>{{ p.api_key_masked }}</code></td>
          <td>{{ p.default_model || '—' }}</td>
          <td class="row">
            <button class="secondary" @click="test(p.id)">测试连通</button>
            <button class="secondary" @click="edit(p)">编辑</button>
            <button class="danger" @click="remove(p.id)">删除</button>
          </td>
        </tr>
        <tr v-if="providers.length === 0"><td colspan="5" class="muted">未配置，将使用平台默认模型</td></tr>
      </tbody>
    </table>
  </div>

  <div class="card">
    <h3>匹配打分权重（四维，默认均等）</h3>
    <div class="row" v-for="d in dimensions" :key="d" style="margin-bottom: 6px">
      <label style="width: 140px; margin: 0">{{ d }}</label>
      <input v-model.number="weights[d]" type="number" min="0" max="100" style="width: 120px" />
    </div>
    <p class="muted">总分 = Σ(维度分 × 权重) / Σ权重；改完权重后可一键重算全部已打分岗位。</p>
    <div class="row" style="margin-top: 12px">
      <button @click="saveWeights">保存权重</button>
      <button class="secondary" :disabled="rescoring" @click="rescore">
        {{ rescoring ? '重算中…' : '按当前权重重算' }}
      </button>
      <span class="muted">{{ weightMessage }}</span>
    </div>
  </div>

  <div class="card">
    <h3>我的调用成本</h3>
    <table>
      <thead><tr><th>任务</th><th>模型</th><th>次数</th><th>输入 tokens</th><th>输出 tokens</th><th>总耗时</th></tr></thead>
      <tbody>
        <tr v-for="c in costs" :key="c.task_type + c.model">
          <td>{{ c.task_type }}</td><td>{{ c.model }}</td><td>{{ c.calls }}</td>
          <td>{{ c.input_tokens }}</td><td>{{ c.output_tokens }}</td><td>{{ (c.duration_ms / 1000).toFixed(1) }}s</td>
        </tr>
        <tr v-if="costs.length === 0"><td colspan="6" class="muted">暂无调用记录</td></tr>
      </tbody>
    </table>
  </div>
</template>

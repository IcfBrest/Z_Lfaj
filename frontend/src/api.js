const BASE = '/api'

async function request(path, options = {}) {
  const token = localStorage.getItem('token')
  const headers = { ...(options.headers || {}) }
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
    options = { ...options, body: JSON.stringify(options.body) }
  }
  const resp = await fetch(BASE + path, { ...options, headers })
  if (resp.status === 401 && !path.startsWith('/auth')) {
    localStorage.removeItem('token')
    location.href = '/login'
    throw new Error('未登录')
  }
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) throw new Error(data.detail || `请求失败（${resp.status}）`)
  return data
}

export const api = {
  get: (p) => request(p),
  post: (p, body) => request(p, { method: 'POST', body }),
  put: (p, body) => request(p, { method: 'PUT', body }),
  del: (p) => request(p, { method: 'DELETE' }),
  upload: (p, formData) => request(p, { method: 'POST', body: formData }),
}

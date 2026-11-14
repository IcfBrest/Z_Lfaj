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
  if (!resp.ok) {
    // detail 可能是字符串，也可能是 {message, ...} 这类结构化错误（如 409 重复投递）
    const detail = data.detail
    const text =
      typeof detail === 'string'
        ? detail
        : detail && detail.message
          ? detail.message
          : `请求失败（${resp.status}）`
    const error = new Error(text)
    error.status = resp.status
    error.detail = detail
    throw error
  }
  return data
}

export const api = {
  get: (p) => request(p),
  post: (p, body) => request(p, { method: 'POST', body }),
  put: (p, body) => request(p, { method: 'PUT', body }),
  patch: (p, body) => request(p, { method: 'PATCH', body }),
  del: (p) => request(p, { method: 'DELETE' }),
  upload: (p, formData) => request(p, { method: 'POST', body: formData }),
}

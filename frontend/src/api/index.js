import axios from 'axios'
import { ElMessage } from 'element-plus'
import { getAuthToken, clearAuthSession } from '@/utils/auth'

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 600000  // 10分钟，长任务用
})

// 自动注入 X-User-Info 头（HMAC 签名 token）
request.interceptors.request.use(
  config => {
    const token = getAuthToken()
    if (token) {
      config.headers['X-User-Info'] = token
    }
    return config
  },
  error => Promise.reject(error)
)

request.interceptors.response.use(
  response => response.data,
  error => {
    const { response } = error
    const message = response?.data?.detail || response?.data?.message || '请求失败'

    // 401 统一处理：清掉登录态，由路由守卫拦截
    if (response?.status === 401) {
      clearAuthSession()
      // 避免在登录页重复提示
      if (window.location.pathname !== '/login') {
        ElMessage.error(message || '登录已过期')
        setTimeout(() => {
          window.location.href = '/login'
        }, 500)
      }
      return Promise.reject(error)
    }

    ElMessage.error(message)
    return Promise.reject(error)
  }
)

export default {
  auth: {
    login: (data) => request.post('/auth/login', data),
    logout: () => request.post('/auth/logout'),
    me: () => request.get('/auth/me'),
    changePassword: (data) => request.post('/auth/change-password', data),
  },

  meeting: {
    list: (params) => request.get('/meetings', { params }).then(res => {
      if (res.items) {
        res.items = res.items.map(item => ({ ...item, id: Number(item.id) }))
      }
      return res
    }),
    get: (id) => request.get(`/meetings/${id}`),
    initUpload: (data) => request.post('/meetings/init-upload', data),
    upload: (id, formData) => request.post(`/meetings/${id}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    }),
    delete: (id) => request.delete(`/meetings/${id}`),
    generateMinutes: (id, data) => request.post(`/meetings/${id}/minutes`, data),
    getTask: (id) => request.get(`/meetings/${id}/task`),
    getPlayUrl: (id) => request.get(`/meetings/${id}/play`),
    exportDocx: (id) => request.get(`/meetings/${id}/export-docx`, { responseType: 'blob' }),
  },

  audit: {
    list: (params) => request.get('/admin/audit-logs', { params }),
    actions: () => request.get('/admin/audit-logs/actions'),
    actors: () => request.get('/admin/audit-logs/actors'),
    export: (params) => request.get('/admin/audit-logs/export', {
      params, responseType: 'blob',
    }),
    // 前端埋点写入入口（任意已登录用户）
    record: (data) => request.post('/admin/audit-logs/record', data),
  },

  transcript: {
    get: (id) => request.get(`/meetings/${id}/transcript`)
  },

  asr: {
    health: () => request.get('/asr/health')
  },

  settings: {
    getLlm: () => request.get('/settings/llm'),
    updateLlm: (data) => request.put('/settings/llm', data),
    testLlm: (data) => request.post('/settings/llm/test', data),

    getAsr: () => request.get('/settings/asr'),
    updateAsr: (data) => request.put('/settings/asr', data),
    testAsr: (data) => request.post('/settings/asr/test', data),

    getTemplates: () => request.get('/settings/templates')
  },

  templates: {
    list: () => request.get('/settings/templates'),
    upsert: (key, content) => request.put('/settings/templates', { key, content }),
    delete: (key) => request.delete(`/settings/templates/${encodeURIComponent(key)}`),
  }
}
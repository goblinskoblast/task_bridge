import axios from 'axios'
import { getTelegramAuthHeaders, getTelegramInitData } from '../utils/telegram'

const API_BASE_URL = '/api'

export const getApiUrl = (endpoint) => `${API_BASE_URL}${endpoint}`

export const getAuthorizedApiUrl = (endpoint) => {
  const initData = getTelegramInitData()
  if (!initData) {
    return getApiUrl(endpoint)
  }

  const separator = endpoint.includes('?') ? '&' : '?'
  return `${API_BASE_URL}${endpoint}${separator}tg_init_data=${encodeURIComponent(initData)}`
}

export const apiFetch = (endpoint, options = {}) => {
  const headers = {
    ...(options.headers || {}),
    ...getTelegramAuthHeaders()
  }

  return fetch(getApiUrl(endpoint), {
    ...options,
    headers
  })
}

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json'
  }
})

api.interceptors.request.use(config => {
  config.headers = {
    ...(config.headers || {}),
    ...getTelegramAuthHeaders()
  }
  return config
})

export const getCurrentUser = async () => {
  const response = await api.get('/me')
  return response.data
}

export const getTasks = async (params = {}) => {
  const response = await api.get('/tasks', { params })
  return response.data
}

export const getTask = async (taskId) => {
  const response = await api.get(`/tasks/${taskId}`)
  return response.data
}

export const updateTaskStatus = async (taskId, status) => {
  const response = await api.patch(`/tasks/${taskId}/status`, null, { params: { status } })
  return response.data
}

export const updateTaskSettings = async (taskId, payload) => {
  const response = await api.patch(`/tasks/${taskId}/settings`, payload)
  return response.data
}

export const updateTaskDueDate = async (taskId, dueDate) => {
  const response = await api.patch(`/tasks/${taskId}/due-date`, {
    due_date: dueDate
  })
  return response.data
}

export const getTaskFiles = async (taskId) => {
  const response = await api.get(`/tasks/${taskId}/files`)
  return response.data
}

export const getTaskComments = async (taskId) => {
  const response = await api.get(`/tasks/${taskId}/comments`)
  return response.data
}

export const createTaskComment = async (taskId, text) => {
  const response = await api.post(`/tasks/${taskId}/comments`, { text })
  return response.data
}

export const getCategories = async () => {
  const response = await api.get('/categories')
  return response.data
}

export const getUsers = async () => {
  const response = await api.get('/users')
  return response.data
}

export const getStats = async (params = {}) => {
  const response = await api.get('/stats', { params })
  return response.data
}

export const addTaskAssignee = async (taskId, userId) => {
  const response = await api.post(`/tasks/${taskId}/assignees`, {
    user_id: userId
  })
  return response.data
}

export const removeTaskAssignee = async (taskId, userId) => {
  const response = await api.delete(`/tasks/${taskId}/assignees/${userId}`)
  return response.data
}

export const deleteTask = async (taskId) => {
  const response = await api.delete(`/tasks/${taskId}`)
  return response.data
}

export default api

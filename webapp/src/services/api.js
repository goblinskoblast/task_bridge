import axios from 'axios'

// Базовый URL API (будет работать через proxy в dev mode)
const API_BASE_URL = '/api'

// Вспомогательная функция для получения полного URL
export const getApiUrl = (endpoint) => {
  // В development используем прокси Vite, в production - относительные пути
  return `${API_BASE_URL}${endpoint}`
}

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json'
  }
})

// Задачи
export const getTasks = async (params = {}) => {
  const response = await api.get('/tasks', { params })
  return response.data
}

export const getTask = async (taskId) => {
  const response = await api.get(`/tasks/${taskId}`)
  return response.data
}

export const updateTaskStatus = async (taskId, status, userId = null) => {
  const params = { status }
  if (userId) {
    params.user_id = userId
  }
  const response = await api.patch(`/tasks/${taskId}/status`, null, { params })
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

// Файлы задач
export const getTaskFiles = async (taskId) => {
  const response = await api.get(`/tasks/${taskId}/files`)
  return response.data
}

// Комментарии
export const getTaskComments = async (taskId) => {
  const response = await api.get(`/tasks/${taskId}/comments`)
  return response.data
}

export const createTaskComment = async (taskId, text, userId) => {
  const response = await api.post(`/tasks/${taskId}/comments`, {
    text,
    user_id: userId
  })
  return response.data
}

// Категории
export const getCategories = async () => {
  const response = await api.get('/categories')
  return response.data
}

// Пользователи
export const getUsers = async (currentUserId = null) => {
  const params = currentUserId ? { current_user_id: currentUserId } : {}
  const response = await api.get('/users', { params })
  return response.data
}

// Статистика
export const getStats = async (params = {}) => {
  const response = await api.get('/stats', { params })
  return response.data
}

// Управление исполнителями
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

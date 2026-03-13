/**
 * Утилиты для форматирования данных
 */

export function formatDate(dateString) {
  if (!dateString) return 'Не указан'

  const date = new Date(dateString)
  const now = new Date()

  // Проверяем, сегодня ли эта дата
  const isToday =
    date.getDate() === now.getDate() &&
    date.getMonth() === now.getMonth() &&
    date.getFullYear() === now.getFullYear()

  // Проверяем, завтра ли эта дата
  const tomorrow = new Date(now)
  tomorrow.setDate(tomorrow.getDate() + 1)
  const isTomorrow =
    date.getDate() === tomorrow.getDate() &&
    date.getMonth() === tomorrow.getMonth() &&
    date.getFullYear() === tomorrow.getFullYear()

  if (isToday) {
    return `Сегодня, ${formatTime(dateString)}`
  } else if (isTomorrow) {
    return `Завтра, ${formatTime(dateString)}`
  } else {
    return `${date.getDate()}.${String(date.getMonth() + 1).padStart(2, '0')}.${date.getFullYear()} ${formatTime(dateString)}`
  }
}

export function formatTime(dateString) {
  if (!dateString) return ''

  const date = new Date(dateString)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

export function formatRelativeTime(dateString) {
  if (!dateString) return null

  const date = new Date(dateString)
  const now = new Date()
  const diffMs = date - now
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  if (diffMs < 0) {
    return 'Просрочено'
  } else if (diffHours < 24) {
    return `Через ${diffHours} ч`
  } else if (diffDays === 1) {
    return 'Завтра'
  } else {
    return `Через ${diffDays} дн`
  }
}

export function formatTimeAgo(dateString) {
  if (!dateString) return null

  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now - date  // Обратный порядок - считаем время назад
  const diffMinutes = Math.floor(diffMs / (1000 * 60))
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  if (diffMinutes < 1) {
    return 'Только что'
  } else if (diffMinutes < 60) {
    return `${diffMinutes} мин назад`
  } else if (diffHours < 24) {
    return `${diffHours} ч назад`
  } else if (diffDays === 1) {
    return 'Вчера'
  } else if (diffDays < 7) {
    return `${diffDays} дн назад`
  } else {
    // Для старых задач показываем полную дату
    return `${date.getDate()}.${String(date.getMonth() + 1).padStart(2, '0')}.${date.getFullYear()}`
  }
}

export function getStatusText(status) {
  const statusMap = {
    pending: 'Ожидает',
    in_progress: 'В работе',
    completed: 'Выполнено',
    cancelled: 'Отменено'
  }
  return statusMap[status] || status
}

export function getPriorityText(priority) {
  const priorityMap = {
    low: 'Низкий',
    normal: 'Обычный',
    high: 'Высокий',
    urgent: 'Срочный'
  }
  return priorityMap[priority] || priority
}

export function getPriorityColor(priority) {
  const colorMap = {
    low: '#6c757d',
    normal: '#0d6efd',
    high: '#fd7e14',
    urgent: '#dc3545'
  }
  return colorMap[priority] || '#0d6efd'
}

export function getStatusColor(status) {
  const colorMap = {
    pending: '#ffc107',
    in_progress: '#0dcaf0',
    completed: '#198754',
    cancelled: '#6c757d'
  }
  return colorMap[status] || '#0dcaf0'
}

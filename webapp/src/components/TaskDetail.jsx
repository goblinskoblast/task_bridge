import { useEffect, useState } from 'react'
import {
  addTaskAssignee,
  createTaskComment,
  deleteTask,
  getTask,
  getTaskComments,
  getTaskFiles,
  getUsers,
  removeTaskAssignee,
  updateTaskDueDate,
  updateTaskSettings,
  updateTaskStatus
} from '../services/api'
import {
  formatDate,
  getPriorityColor,
  getPriorityText,
  getStatusColor,
  getStatusText
} from '../utils/format'
import { showTelegramAlert, showTelegramConfirm } from '../utils/telegram'

const REMINDER_OPTIONS = [
  { value: '', label: 'По умолчанию' },
  { value: '2', label: 'Каждые 2 часа' },
  { value: '3', label: 'Каждые 3 часа' },
  { value: '6', label: 'Каждые 6 часов' },
  { value: '12', label: 'Каждые 12 часов' },
  { value: '24', label: 'Каждые 24 часа' }
]

function toDateTimeLocalValue(value) {
  if (!value) return ''
  const date = new Date(value)
  const timezoneOffsetMs = date.getTimezoneOffset() * 60 * 1000
  return new Date(date.getTime() - timezoneOffsetMs).toISOString().slice(0, 16)
}

export function TaskDetail({ task: initialTask, onBack, isManager, currentUserId }) {
  const [task, setTask] = useState(initialTask)
  const [comments, setComments] = useState([])
  const [files, setFiles] = useState([])
  const [users, setUsers] = useState([])
  const [newComment, setNewComment] = useState('')
  const [loading, setLoading] = useState(false)
  const [showAssigneeModal, setShowAssigneeModal] = useState(false)
  const [assigneeSearch, setAssigneeSearch] = useState('')
  const [savingSettings, setSavingSettings] = useState(false)
  const [dueDateInput, setDueDateInput] = useState(toDateTimeLocalValue(initialTask.due_date))
  const [savingDueDate, setSavingDueDate] = useState(false)

  useEffect(() => {
    loadTaskData()
  }, [task.id])

  useEffect(() => {
    setDueDateInput(toDateTimeLocalValue(task.due_date))
  }, [task.due_date])

  async function loadTaskData() {
    try {
      setLoading(true)
      const [taskData, commentsData, filesData, usersData] = await Promise.all([
        getTask(task.id),
        getTaskComments(task.id),
        getTaskFiles(task.id),
        isManager && currentUserId ? getUsers() : Promise.resolve([])
      ])

      setTask(taskData)
      setComments(commentsData)
      setFiles(filesData)
      setUsers(usersData)
    } catch (err) {
      console.error('Error loading task data:', err)
      showTelegramAlert('Ошибка загрузки данных')
    } finally {
      setLoading(false)
    }
  }

  async function handleStatusChange(newStatus) {
    try {
      await updateTaskStatus(task.id, newStatus)
      setTask(prev => ({ ...prev, status: newStatus }))
      showTelegramAlert('Статус обновлен')
    } catch (err) {
      console.error('Error updating status:', err)
      showTelegramAlert('Ошибка обновления статуса')
    }
  }

  async function handleReminderIntervalChange(event) {
    const value = event.target.value

    try {
      setSavingSettings(true)
      const updatedTask = await updateTaskSettings(task.id, {
        reminder_interval_hours: value ? parseInt(value, 10) : null
      })
      setTask(updatedTask)
      showTelegramAlert('Настройки напоминаний обновлены')
    } catch (err) {
      console.error('Error updating reminder settings:', err)
      showTelegramAlert('Ошибка обновления настроек задачи')
    } finally {
      setSavingSettings(false)
    }
  }

  async function handleDueDateSave() {
    try {
      setSavingDueDate(true)
      const updatedTask = await updateTaskDueDate(task.id, dueDateInput || null)
      setTask(updatedTask)
      showTelegramAlert('Срок обновлен')
    } catch (err) {
      console.error('Error updating due date:', err)
      showTelegramAlert('Ошибка обновления срока')
    } finally {
      setSavingDueDate(false)
    }
  }

  async function handleAddComment() {
    if (!newComment.trim() || !currentUserId) return

    try {
      const comment = await createTaskComment(task.id, newComment)
      setComments([...comments, comment])
      setNewComment('')
    } catch (err) {
      console.error('Error adding comment:', err)
      showTelegramAlert('Ошибка добавления комментария')
    }
  }

  async function handleAddAssignee(userId) {
    try {
      await addTaskAssignee(task.id, userId)
      await loadTaskData()
      setShowAssigneeModal(false)
      setAssigneeSearch('')
      showTelegramAlert('Исполнитель добавлен')
    } catch (err) {
      console.error('Error adding assignee:', err)
      showTelegramAlert(err.response?.data?.detail || 'Ошибка добавления исполнителя')
    }
  }

  async function handleRemoveAssignee(userId) {
    showTelegramConfirm('Удалить исполнителя?', async confirmed => {
      if (!confirmed) return

      try {
        await removeTaskAssignee(task.id, userId)
        await loadTaskData()
        showTelegramAlert('Исполнитель удален')
      } catch (err) {
        console.error('Error removing assignee:', err)
        showTelegramAlert('Ошибка удаления исполнителя')
      }
    })
  }

  async function handleDeleteTask() {
    showTelegramConfirm('Вы точно хотите удалить эту задачу?', async confirmed => {
      if (!confirmed) return

      try {
        await deleteTask(task.id)
        showTelegramAlert('Задача удалена')
        onBack()
      } catch (err) {
        console.error('Error deleting task:', err)
        showTelegramAlert('Ошибка удаления задачи')
      }
    })
  }

  const statusActions = {}

  if (isManager) {
    statusActions.pending = [
      { status: 'in_progress', label: 'Начать работу', color: '#0dcaf0' },
      { status: 'cancelled', label: 'Отменить', color: '#6c757d' }
    ]
    statusActions.in_progress = [
      { status: 'completed', label: 'Завершить', color: '#198754' },
      { status: 'pending', label: 'Вернуть в ожидание', color: '#ffc107' }
    ]
    statusActions.completed = [
      { status: 'in_progress', label: 'Возобновить', color: '#0dcaf0' }
    ]
    statusActions.cancelled = [
      { status: 'pending', label: 'Восстановить', color: '#ffc107' }
    ]
  } else {
    statusActions.pending = [
      { status: 'in_progress', label: 'Начать работу', color: '#0dcaf0' }
    ]
    statusActions.in_progress = [
      { status: 'completed', label: 'Завершить', color: '#198754' }
    ]
  }

  const availableUsers = users.filter(
    user => !task.assignees.some(assignee => assignee.id === user.id)
  )

  const filteredUsers = availableUsers.filter(user => {
    if (!assigneeSearch.trim()) return true

    const searchLower = assigneeSearch.toLowerCase()
    const firstName = (user.first_name || '').toLowerCase()
    const username = (user.username || '').toLowerCase()

    return firstName.includes(searchLower) || username.includes(searchLower)
  })

  const effectiveReminderHours =
    task.effective_reminder_interval_hours || task.default_reminder_interval_hours || 3

  return (
    <div className="task-detail">
      <div className="task-detail-header">
        <button className="back-button" onClick={onBack}>
          ← Назад
        </button>
        <h2>{task.title}</h2>
      </div>

      <div className="task-detail-content">
        <div className="task-info-section">
          <div className="info-row">
            <span className="info-label">Статус:</span>
            <span className="info-value" style={{ color: getStatusColor(task.status), fontWeight: 'bold' }}>
              {getStatusText(task.status)}
            </span>
          </div>

          <div className="info-row">
            <span className="info-label">Приоритет:</span>
            <span className="info-value" style={{ color: getPriorityColor(task.priority), fontWeight: 'bold' }}>
              {getPriorityText(task.priority)}
            </span>
          </div>

          <div className="info-row info-row-due-date">
            <span className="info-label">Срок:</span>
            {isManager ? (
              <div className="due-date-editor">
                <input
                  type="datetime-local"
                  className="task-due-date-input"
                  value={dueDateInput}
                  onChange={e => setDueDateInput(e.target.value)}
                />
                <button
                  className="task-due-date-button"
                  onClick={handleDueDateSave}
                  disabled={savingDueDate}
                >
                  {savingDueDate ? '...' : 'Сохранить'}
                </button>
                <button
                  className="task-due-date-button task-due-date-button-secondary"
                  onClick={() => setDueDateInput('')}
                  disabled={savingDueDate}
                >
                  Очистить
                </button>
                <span className="task-due-date-preview">
                  {task.due_date ? formatDate(task.due_date) : 'Не указан'}
                </span>
              </div>
            ) : (
              <span className="info-value">{task.due_date ? formatDate(task.due_date) : 'Не указан'}</span>
            )}
          </div>

          {task.category && (
            <div className="info-row">
              <span className="info-label">Категория:</span>
              <span className="info-value">{task.category.name}</span>
            </div>
          )}

          {task.creator && (
            <div className="info-row">
              <span className="info-label">Создатель:</span>
              <span className="info-value">{task.creator.first_name || task.creator.username}</span>
            </div>
          )}

          {task.created_at && (
            <div className="info-row">
              <span className="info-label">Создана:</span>
              <span className="info-value">{formatDate(task.created_at)}</span>
            </div>
          )}

          <div className="info-row info-row-settings">
            <span className="info-label">Напоминания:</span>
            {isManager ? (
              <select
                className="form-select task-settings-select"
                value={task.reminder_interval_hours ?? ''}
                onChange={handleReminderIntervalChange}
                disabled={savingSettings}
              >
                {REMINDER_OPTIONS.map(option => (
                  <option key={option.value || 'default'} value={option.value}>
                    {option.value === '' ? `${option.label} (${effectiveReminderHours} ч)` : option.label}
                  </option>
                ))}
              </select>
            ) : (
              <span className="info-value">Каждые {effectiveReminderHours} ч</span>
            )}
          </div>
        </div>

        <div className="task-description-section">
          <h3>Описание</h3>
          <p>{task.description}</p>
        </div>

        <div className="task-assignees-section">
          <div className="section-header">
            <h3>Исполнители</h3>
            {isManager && (
              <button className="add-assignee-button" onClick={() => setShowAssigneeModal(true)}>
                + Добавить
              </button>
            )}
          </div>

          <div className="assignees-list">
            {task.assignees && task.assignees.length > 0 ? (
              task.assignees.map(assignee => (
                <div key={assignee.id} className="assignee-item">
                  <span className="assignee-name">{assignee.first_name || assignee.username}</span>
                  {isManager && (
                    <button className="remove-assignee-button" onClick={() => handleRemoveAssignee(assignee.id)}>
                      ✕
                    </button>
                  )}
                </div>
              ))
            ) : (
              <p className="no-assignees">Нет назначенных исполнителей</p>
            )}
          </div>
        </div>

        {showAssigneeModal && (
          <div className="modal-overlay" onClick={() => { setShowAssigneeModal(false); setAssigneeSearch('') }}>
            <div className="modal-content" onClick={e => e.stopPropagation()}>
              <h3>Добавить исполнителя</h3>

              <input
                type="text"
                className="assignee-search-input"
                placeholder="Поиск по имени или username..."
                value={assigneeSearch}
                onChange={e => setAssigneeSearch(e.target.value)}
                autoFocus
              />

              <div className="user-list">
                {filteredUsers.length > 0 ? (
                  filteredUsers.map(user => (
                    <div key={user.id} className="user-item" onClick={() => handleAddAssignee(user.id)}>
                      <span>{user.first_name || user.username}</span>
                    </div>
                  ))
                ) : availableUsers.length === 0 ? (
                  <p>Все пользователи уже назначены</p>
                ) : (
                  <p>Ничего не найдено</p>
                )}
              </div>
              <button className="modal-close-button" onClick={() => { setShowAssigneeModal(false); setAssigneeSearch('') }}>
                Закрыть
              </button>
            </div>
          </div>
        )}

        <div className="task-actions-section">
          <h3>Действия</h3>
          <div className="status-actions">
            {(statusActions[task.status] || []).map(action => (
              <button
                key={action.status}
                className="status-action-button"
                style={{ backgroundColor: action.color }}
                onClick={() => handleStatusChange(action.status)}
              >
                {action.label}
              </button>
            ))}

            {isManager && (
              <button className="status-action-button delete-button" onClick={handleDeleteTask}>
                Удалить задачу
              </button>
            )}
          </div>
        </div>

        <div className="task-comments-section">
          <h3>Комментарии</h3>
          <div className="comments-list">
            {comments.length > 0 ? (
              comments.map(comment => (
                <div key={comment.id} className="comment-item">
                  <div className="comment-header">
                    <span className="comment-author">{comment.author?.first_name || comment.author?.username || 'Пользователь'}</span>
                    <span className="comment-date">{formatDate(comment.created_at)}</span>
                  </div>
                  <div className="comment-text">{comment.text}</div>
                </div>
              ))
            ) : (
              <p className="no-comments">Комментариев пока нет</p>
            )}
          </div>

          <div className="comment-form">
            <textarea
              className="comment-input"
              placeholder="Добавить комментарий..."
              value={newComment}
              onChange={e => setNewComment(e.target.value)}
              rows={3}
            />
            <button className="add-comment-button" onClick={handleAddComment} disabled={!newComment.trim() || !currentUserId}>
              Отправить
            </button>
          </div>
        </div>

        <div className="task-files-section">
          <h3>Файлы</h3>
          {loading ? (
            <p>Загрузка...</p>
          ) : files.length > 0 ? (
            <div className="files-list">
              {files.map(file => (
                <div key={file.id} className="file-item">
                  <span className="file-name">{file.file_name || 'Файл'}</span>
                  <span className="file-meta">{formatDate(file.created_at)}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="no-files">Файлы пока не прикреплены</p>
          )}
        </div>
      </div>
    </div>
  )
}

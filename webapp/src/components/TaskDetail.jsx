import { useState, useEffect } from 'react'
import {
  getTask,
  updateTaskStatus,
  getTaskComments,
  createTaskComment,
  getTaskFiles,
  getUsers,
  addTaskAssignee,
  removeTaskAssignee,
  deleteTask
} from '../services/api'
import { formatDate, getStatusText, getPriorityText, getPriorityColor, getStatusColor } from '../utils/format'
import { showTelegramAlert, showTelegramConfirm } from '../utils/telegram'

export function TaskDetail({ task: initialTask, onBack, isManager }) {
  const [task, setTask] = useState(initialTask)
  const [comments, setComments] = useState([])
  const [files, setFiles] = useState([])
  const [users, setUsers] = useState([])
  const [newComment, setNewComment] = useState('')
  const [loading, setLoading] = useState(false)
  const [showAssigneeModal, setShowAssigneeModal] = useState(false)
  const [assigneeSearch, setAssigneeSearch] = useState('')

  useEffect(() => {
    loadTaskData()
  }, [task.id])

  async function loadTaskData() {
    try {
      setLoading(true)

      // SECURITY: Получаем текущий userId для фильтрации пользователей
      const userId = new URLSearchParams(window.location.search).get('user_id')

      const [taskData, commentsData, filesData, usersData] = await Promise.all([
        getTask(task.id),
        getTaskComments(task.id),
        getTaskFiles(task.id),
        isManager ? getUsers(parseInt(userId)) : Promise.resolve([])
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
      const userId = new URLSearchParams(window.location.search).get('user_id')
      await updateTaskStatus(task.id, newStatus, parseInt(userId))
      setTask({ ...task, status: newStatus })
      showTelegramAlert('Статус обновлен')
    } catch (err) {
      console.error('Error updating status:', err)
      showTelegramAlert('Ошибка обновления статуса')
    }
  }

  async function handleAddComment() {
    if (!newComment.trim()) return

    try {
      const userId = new URLSearchParams(window.location.search).get('user_id')
      const comment = await createTaskComment(task.id, newComment, parseInt(userId))
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
      await loadTaskData() // Перезагружаем данные задачи
      setShowAssigneeModal(false)
      setAssigneeSearch('') // Сбрасываем поиск
      showTelegramAlert('Исполнитель добавлен')
    } catch (err) {
      console.error('Error adding assignee:', err)
      showTelegramAlert(err.response?.data?.detail || 'Ошибка добавления исполнителя')
    }
  }

  async function handleRemoveAssignee(userId) {
    showTelegramConfirm('Удалить исполнителя?', async (confirmed) => {
      if (!confirmed) return

      try {
        await removeTaskAssignee(task.id, userId)
        await loadTaskData() // Перезагружаем данные задачи
        showTelegramAlert('Исполнитель удален')
      } catch (err) {
        console.error('Error removing assignee:', err)
        showTelegramAlert('Ошибка удаления исполнителя')
      }
    })
  }

  async function handleDeleteTask() {
    showTelegramConfirm('Вы точно хотите удалить эту задачу?', async (confirmed) => {
      if (!confirmed) return

      try {
        await deleteTask(task.id)
        showTelegramAlert('Задача удалена')
        onBack() // Возвращаемся к списку задач
      } catch (err) {
        console.error('Error deleting task:', err)
        showTelegramAlert('Ошибка удаления задачи')
      }
    })
  }

  // Определяем доступные действия в зависимости от роли
  const statusActions = {}

  if (isManager) {
    // Создатель задачи может делать всё
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
    // Исполнитель может только начать работу и завершить
    statusActions.pending = [
      { status: 'in_progress', label: 'Начать работу', color: '#0dcaf0' }
    ]
    statusActions.in_progress = [
      { status: 'completed', label: 'Завершить', color: '#198754' }
    ]
  }

  // Фильтруем пользователей, которые еще не назначены
  const availableUsers = users.filter(
    user => !task.assignees.some(assignee => assignee.id === user.id)
  )

  // Фильтруем по поисковому запросу
  const filteredUsers = availableUsers.filter(user => {
    if (!assigneeSearch.trim()) return true

    const searchLower = assigneeSearch.toLowerCase()
    const firstName = (user.first_name || '').toLowerCase()
    const username = (user.username || '').toLowerCase()

    return firstName.includes(searchLower) || username.includes(searchLower)
  })

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
            <span
              className="info-value"
              style={{ color: getStatusColor(task.status), fontWeight: 'bold' }}
            >
              {getStatusText(task.status)}
            </span>
          </div>

          <div className="info-row">
            <span className="info-label">Приоритет:</span>
            <span
              className="info-value"
              style={{ color: getPriorityColor(task.priority), fontWeight: 'bold' }}
            >
              {getPriorityText(task.priority)}
            </span>
          </div>

          {task.due_date && (
            <div className="info-row">
              <span className="info-label">Срок:</span>
              <span className="info-value">{formatDate(task.due_date)}</span>
            </div>
          )}

          {task.category && (
            <div className="info-row">
              <span className="info-label">Категория:</span>
              <span className="info-value">{task.category.name}</span>
            </div>
          )}

          {task.creator && (
            <div className="info-row">
              <span className="info-label">Создатель:</span>
              <span className="info-value">
                {task.creator.first_name || task.creator.username}
              </span>
            </div>
          )}

          {task.created_at && (
            <div className="info-row">
              <span className="info-label">Создана:</span>
              <span className="info-value">{formatDate(task.created_at)}</span>
            </div>
          )}
        </div>

        <div className="task-description-section">
          <h3>Описание</h3>
          <p>{task.description}</p>
        </div>

        <div className="task-assignees-section">
          <div className="section-header">
            <h3>Исполнители</h3>
            {isManager && (
              <button
                className="add-assignee-button"
                onClick={() => setShowAssigneeModal(true)}
              >
                + Добавить
              </button>
            )}
          </div>

          <div className="assignees-list">
            {task.assignees && task.assignees.length > 0 ? (
              task.assignees.map(assignee => (
                <div key={assignee.id} className="assignee-item">
                  <span className="assignee-name">
                    {assignee.first_name || assignee.username}
                  </span>
                  {isManager && (
                    <button
                      className="remove-assignee-button"
                      onClick={() => handleRemoveAssignee(assignee.id)}
                    >
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

        {/* Модальное окно для добавления исполнителя */}
        {showAssigneeModal && (
          <div className="modal-overlay" onClick={() => {
            setShowAssigneeModal(false)
            setAssigneeSearch('')
          }}>
            <div className="modal-content" onClick={(e) => e.stopPropagation()}>
              <h3>Добавить исполнителя</h3>

              {/* Поисковая строка */}
              <input
                type="text"
                className="assignee-search-input"
                placeholder="Поиск по имени или username..."
                value={assigneeSearch}
                onChange={(e) => setAssigneeSearch(e.target.value)}
                autoFocus
              />

              <div className="user-list">
                {filteredUsers.length > 0 ? (
                  filteredUsers.map(user => (
                    <div
                      key={user.id}
                      className="user-item"
                      onClick={() => handleAddAssignee(user.id)}
                    >
                      <span>{user.first_name || user.username}</span>
                    </div>
                  ))
                ) : availableUsers.length === 0 ? (
                  <p>Все пользователи уже назначены</p>
                ) : (
                  <p>Ничего не найдено</p>
                )}
              </div>
              <button
                className="modal-close-button"
                onClick={() => {
                  setShowAssigneeModal(false)
                  setAssigneeSearch('')
                }}
              >
                Закрыть
              </button>
            </div>
          </div>
        )}

        {/* Действия со статусом */}
        {statusActions[task.status] && statusActions[task.status].length > 0 && (
          <div className="task-actions-section">
            <h3>Действия</h3>
            <div className="status-actions">
              {statusActions[task.status].map(action => (
                <button
                  key={action.status}
                  className="status-action-button"
                  style={{ backgroundColor: action.color }}
                  onClick={() => handleStatusChange(action.status)}
                >
                  {action.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Кнопка удаления задачи - только для создателя */}
        {isManager && (
          <div className="task-danger-section">
            <button
              className="delete-task-button"
              onClick={handleDeleteTask}
            >
              🗑️ Удалить задачу
            </button>
          </div>
        )}

        {/* Файлы */}
        {files.length > 0 && (
          <div className="task-files-section">
            <h3>Файлы ({files.length})</h3>
            <div className="files-list">
              {files.map(file => (
                <div key={file.id} className="file-item">
                  <span className="file-name">{file.file_name || file.file_type}</span>
                  <span className="file-uploader">
                    {file.uploaded_by?.first_name || file.uploaded_by?.username}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Комментарии */}
        <div className="task-comments-section">
          <h3>Комментарии ({comments.length})</h3>

          <div className="comments-list">
            {comments.map(comment => (
              <div key={comment.id} className="comment-item">
                <div className="comment-header">
                  <span className="comment-author">
                    {comment.author?.first_name || comment.author?.username}
                  </span>
                  <span className="comment-date">
                    {formatDate(comment.created_at)}
                  </span>
                </div>
                <p className="comment-text">{comment.text}</p>
              </div>
            ))}
          </div>

          <div className="add-comment">
            <textarea
              value={newComment}
              onChange={(e) => setNewComment(e.target.value)}
              placeholder="Добавить комментарий..."
              rows={3}
            />
            <button
              className="add-comment-button"
              onClick={handleAddComment}
              disabled={!newComment.trim()}
            >
              Отправить
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

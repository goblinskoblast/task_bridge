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
  { value: '', label: 'РџРѕ СѓРјРѕР»С‡Р°РЅРёСЋ' },
  { value: '2', label: 'РљР°Р¶РґС‹Рµ 2 С‡Р°СЃР°' },
  { value: '3', label: 'РљР°Р¶РґС‹Рµ 3 С‡Р°СЃР°' },
  { value: '6', label: 'РљР°Р¶РґС‹Рµ 6 С‡Р°СЃРѕРІ' },
  { value: '12', label: 'РљР°Р¶РґС‹Рµ 12 С‡Р°СЃРѕРІ' },
  { value: '24', label: 'РљР°Р¶РґС‹Рµ 24 С‡Р°СЃР°' }
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
        isManager && currentUserId ? getUsers(currentUserId) : Promise.resolve([])
      ])

      setTask(taskData)
      setComments(commentsData)
      setFiles(filesData)
      setUsers(usersData)
    } catch (err) {
      console.error('Error loading task data:', err)
      showTelegramAlert('РћС€РёР±РєР° Р·Р°РіСЂСѓР·РєРё РґР°РЅРЅС‹С…')
    } finally {
      setLoading(false)
    }
  }

  async function handleStatusChange(newStatus) {
    try {
      await updateTaskStatus(task.id, newStatus, currentUserId)
      setTask(prev => ({ ...prev, status: newStatus }))
      showTelegramAlert('РЎС‚Р°С‚СѓСЃ РѕР±РЅРѕРІР»РµРЅ')
    } catch (err) {
      console.error('Error updating status:', err)
      showTelegramAlert('РћС€РёР±РєР° РѕР±РЅРѕРІР»РµРЅРёСЏ СЃС‚Р°С‚СѓСЃР°')
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
      showTelegramAlert('РќР°СЃС‚СЂРѕР№РєРё РЅР°РїРѕРјРёРЅР°РЅРёР№ РѕР±РЅРѕРІР»РµРЅС‹')
    } catch (err) {
      console.error('Error updating reminder settings:', err)
      showTelegramAlert('РћС€РёР±РєР° РѕР±РЅРѕРІР»РµРЅРёСЏ РЅР°СЃС‚СЂРѕРµРє Р·Р°РґР°С‡Рё')
    } finally {
      setSavingSettings(false)
    }
  }

  async function handleDueDateSave() {
    try {
      setSavingDueDate(true)
      const updatedTask = await updateTaskDueDate(task.id, dueDateInput || null)
      setTask(updatedTask)
      showTelegramAlert('РЎСЂРѕРє РѕР±РЅРѕРІР»РµРЅ')
    } catch (err) {
      console.error('Error updating due date:', err)
      showTelegramAlert('РћС€РёР±РєР° РѕР±РЅРѕРІР»РµРЅРёСЏ СЃСЂРѕРєР°')
    } finally {
      setSavingDueDate(false)
    }
  }

  async function handleAddComment() {
    if (!newComment.trim() || !currentUserId) return

    try {
      const comment = await createTaskComment(task.id, newComment, currentUserId)
      setComments([...comments, comment])
      setNewComment('')
    } catch (err) {
      console.error('Error adding comment:', err)
      showTelegramAlert('РћС€РёР±РєР° РґРѕР±Р°РІР»РµРЅРёСЏ РєРѕРјРјРµРЅС‚Р°СЂРёСЏ')
    }
  }

  async function handleAddAssignee(userId) {
    try {
      await addTaskAssignee(task.id, userId)
      await loadTaskData()
      setShowAssigneeModal(false)
      setAssigneeSearch('')
      showTelegramAlert('РСЃРїРѕР»РЅРёС‚РµР»СЊ РґРѕР±Р°РІР»РµРЅ')
    } catch (err) {
      console.error('Error adding assignee:', err)
      showTelegramAlert(err.response?.data?.detail || 'РћС€РёР±РєР° РґРѕР±Р°РІР»РµРЅРёСЏ РёСЃРїРѕР»РЅРёС‚РµР»СЏ')
    }
  }

  async function handleRemoveAssignee(userId) {
    showTelegramConfirm('РЈРґР°Р»РёС‚СЊ РёСЃРїРѕР»РЅРёС‚РµР»СЏ?', async confirmed => {
      if (!confirmed) return

      try {
        await removeTaskAssignee(task.id, userId)
        await loadTaskData()
        showTelegramAlert('РСЃРїРѕР»РЅРёС‚РµР»СЊ СѓРґР°Р»РµРЅ')
      } catch (err) {
        console.error('Error removing assignee:', err)
        showTelegramAlert('РћС€РёР±РєР° СѓРґР°Р»РµРЅРёСЏ РёСЃРїРѕР»РЅРёС‚РµР»СЏ')
      }
    })
  }

  async function handleDeleteTask() {
    showTelegramConfirm('Р’С‹ С‚РѕС‡РЅРѕ С…РѕС‚РёС‚Рµ СѓРґР°Р»РёС‚СЊ СЌС‚Сѓ Р·Р°РґР°С‡Сѓ?', async confirmed => {
      if (!confirmed) return

      try {
        await deleteTask(task.id)
        showTelegramAlert('Р—Р°РґР°С‡Р° СѓРґР°Р»РµРЅР°')
        onBack()
      } catch (err) {
        console.error('Error deleting task:', err)
        showTelegramAlert('РћС€РёР±РєР° СѓРґР°Р»РµРЅРёСЏ Р·Р°РґР°С‡Рё')
      }
    })
  }

  const statusActions = {}

  if (isManager) {
    statusActions.pending = [
      { status: 'in_progress', label: 'РќР°С‡Р°С‚СЊ СЂР°Р±РѕС‚Сѓ', color: '#0dcaf0' },
      { status: 'cancelled', label: 'РћС‚РјРµРЅРёС‚СЊ', color: '#6c757d' }
    ]
    statusActions.in_progress = [
      { status: 'completed', label: 'Р—Р°РІРµСЂС€РёС‚СЊ', color: '#198754' },
      { status: 'pending', label: 'Р’РµСЂРЅСѓС‚СЊ РІ РѕР¶РёРґР°РЅРёРµ', color: '#ffc107' }
    ]
    statusActions.completed = [
      { status: 'in_progress', label: 'Р’РѕР·РѕР±РЅРѕРІРёС‚СЊ', color: '#0dcaf0' }
    ]
    statusActions.cancelled = [
      { status: 'pending', label: 'Р’РѕСЃСЃС‚Р°РЅРѕРІРёС‚СЊ', color: '#ffc107' }
    ]
  } else {
    statusActions.pending = [
      { status: 'in_progress', label: 'РќР°С‡Р°С‚СЊ СЂР°Р±РѕС‚Сѓ', color: '#0dcaf0' }
    ]
    statusActions.in_progress = [
      { status: 'completed', label: 'Р—Р°РІРµСЂС€РёС‚СЊ', color: '#198754' }
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
          в†ђ РќР°Р·Р°Рґ
        </button>
        <h2>{task.title}</h2>
      </div>

      <div className="task-detail-content">
        <div className="task-info-section">
          <div className="info-row">
            <span className="info-label">РЎС‚Р°С‚СѓСЃ:</span>
            <span className="info-value" style={{ color: getStatusColor(task.status), fontWeight: 'bold' }}>
              {getStatusText(task.status)}
            </span>
          </div>

          <div className="info-row">
            <span className="info-label">РџСЂРёРѕСЂРёС‚РµС‚:</span>
            <span className="info-value" style={{ color: getPriorityColor(task.priority), fontWeight: 'bold' }}>
              {getPriorityText(task.priority)}
            </span>
          </div>

          <div className="info-row info-row-due-date">
            <span className="info-label">РЎСЂРѕРє:</span>
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
                  {savingDueDate ? '...' : 'РЎРѕС…СЂР°РЅРёС‚СЊ'}
                </button>
                <button
                  className="task-due-date-button task-due-date-button-secondary"
                  onClick={() => setDueDateInput('')}
                  disabled={savingDueDate}
                >
                  РћС‡РёСЃС‚РёС‚СЊ
                </button>
                <span className="task-due-date-preview">
                  {task.due_date ? formatDate(task.due_date) : 'РќРµ СѓРєР°Р·Р°РЅ'}
                </span>
              </div>
            ) : (
              <span className="info-value">{task.due_date ? formatDate(task.due_date) : 'РќРµ СѓРєР°Р·Р°РЅ'}</span>
            )}
          </div>

          {task.category && (
            <div className="info-row">
              <span className="info-label">РљР°С‚РµРіРѕСЂРёСЏ:</span>
              <span className="info-value">{task.category.name}</span>
            </div>
          )}

          {task.creator && (
            <div className="info-row">
              <span className="info-label">РЎРѕР·РґР°С‚РµР»СЊ:</span>
              <span className="info-value">{task.creator.first_name || task.creator.username}</span>
            </div>
          )}

          {task.created_at && (
            <div className="info-row">
              <span className="info-label">РЎРѕР·РґР°РЅР°:</span>
              <span className="info-value">{formatDate(task.created_at)}</span>
            </div>
          )}

          <div className="info-row info-row-settings">
            <span className="info-label">РќР°РїРѕРјРёРЅР°РЅРёСЏ:</span>
            {isManager ? (
              <select
                className="form-select task-settings-select"
                value={task.reminder_interval_hours ?? ''}
                onChange={handleReminderIntervalChange}
                disabled={savingSettings}
              >
                {REMINDER_OPTIONS.map(option => (
                  <option key={option.value || 'default'} value={option.value}>
                    {option.value === '' ? `${option.label} (${effectiveReminderHours} С‡)` : option.label}
                  </option>
                ))}
              </select>
            ) : (
              <span className="info-value">РљР°Р¶РґС‹Рµ {effectiveReminderHours} С‡</span>
            )}
          </div>
        </div>

        <div className="task-description-section">
          <h3>РћРїРёСЃР°РЅРёРµ</h3>
          <p>{task.description}</p>
        </div>

        <div className="task-assignees-section">
          <div className="section-header">
            <h3>РСЃРїРѕР»РЅРёС‚РµР»Рё</h3>
            {isManager && (
              <button className="add-assignee-button" onClick={() => setShowAssigneeModal(true)}>
                + Р”РѕР±Р°РІРёС‚СЊ
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
                      вњ•
                    </button>
                  )}
                </div>
              ))
            ) : (
              <p className="no-assignees">РќРµС‚ РЅР°Р·РЅР°С‡РµРЅРЅС‹С… РёСЃРїРѕР»РЅРёС‚РµР»РµР№</p>
            )}
          </div>
        </div>

        {showAssigneeModal && (
          <div className="modal-overlay" onClick={() => { setShowAssigneeModal(false); setAssigneeSearch('') }}>
            <div className="modal-content" onClick={e => e.stopPropagation()}>
              <h3>Р”РѕР±Р°РІРёС‚СЊ РёСЃРїРѕР»РЅРёС‚РµР»СЏ</h3>

              <input
                type="text"
                className="assignee-search-input"
                placeholder="РџРѕРёСЃРє РїРѕ РёРјРµРЅРё РёР»Рё username..."
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
                  <p>Р’СЃРµ РїРѕР»СЊР·РѕРІР°С‚РµР»Рё СѓР¶Рµ РЅР°Р·РЅР°С‡РµРЅС‹</p>
                ) : (
                  <p>РќРёС‡РµРіРѕ РЅРµ РЅР°Р№РґРµРЅРѕ</p>
                )}
              </div>
              <button className="modal-close-button" onClick={() => { setShowAssigneeModal(false); setAssigneeSearch('') }}>
                Р—Р°РєСЂС‹С‚СЊ
              </button>
            </div>
          </div>
        )}

        <div className="task-actions-section">
          <h3>Р”РµР№СЃС‚РІРёСЏ</h3>
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
                РЈРґР°Р»РёС‚СЊ Р·Р°РґР°С‡Сѓ
              </button>
            )}
          </div>
        </div>

        <div className="task-comments-section">
          <h3>РљРѕРјРјРµРЅС‚Р°СЂРёРё</h3>
          <div className="comments-list">
            {comments.length > 0 ? (
              comments.map(comment => (
                <div key={comment.id} className="comment-item">
                  <div className="comment-header">
                    <span className="comment-author">{comment.author?.first_name || comment.author?.username || 'РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ'}</span>
                    <span className="comment-date">{formatDate(comment.created_at)}</span>
                  </div>
                  <div className="comment-text">{comment.text}</div>
                </div>
              ))
            ) : (
              <p className="no-comments">РљРѕРјРјРµРЅС‚Р°СЂРёРµРІ РїРѕРєР° РЅРµС‚</p>
            )}
          </div>

          <div className="comment-form">
            <textarea
              className="comment-input"
              placeholder="Р”РѕР±Р°РІРёС‚СЊ РєРѕРјРјРµРЅС‚Р°СЂРёР№..."
              value={newComment}
              onChange={e => setNewComment(e.target.value)}
              rows={3}
            />
            <button className="add-comment-button" onClick={handleAddComment} disabled={!newComment.trim() || !currentUserId}>
              РћС‚РїСЂР°РІРёС‚СЊ
            </button>
          </div>
        </div>

        <div className="task-files-section">
          <h3>Р¤Р°Р№Р»С‹</h3>
          {loading ? (
            <p>Р—Р°РіСЂСѓР·РєР°...</p>
          ) : files.length > 0 ? (
            <div className="files-list">
              {files.map(file => (
                <div key={file.id} className="file-item">
                  <span className="file-name">{file.file_name || 'Р¤Р°Р№Р»'}</span>
                  <span className="file-meta">{formatDate(file.created_at)}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="no-files">Р¤Р°Р№Р»С‹ РїРѕРєР° РЅРµ РїСЂРёРєСЂРµРїР»РµРЅС‹</p>
          )}
        </div>
      </div>
    </div>
  )
}

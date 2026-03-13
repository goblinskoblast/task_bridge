import { getStatusText, getPriorityText, formatRelativeTime, formatTimeAgo } from '../utils/format'

export function TaskList({ tasks, onTaskClick, loading }) {
  if (loading) {
    return (
      <div className="task-list-loading">
        <div className="loading-spinner"></div>
      </div>
    )
  }

  return (
    <div className="task-list">
      {tasks.map(task => (
        <div
          key={task.id}
          className={`task-card task-card-${task.status} task-card-priority-${task.priority}`}
          onClick={() => onTaskClick(task)}
        >
          <div className="task-card-header">
            <h3 className="task-title">{task.title}</h3>
            <span className={`task-priority priority-${task.priority}`}>
              {getPriorityText(task.priority)}
            </span>
          </div>

          <p className="task-description">{task.description}</p>

          <div className="task-meta">
            <div className="task-assignees">
              {task.assignees && task.assignees.length > 0 ? (
                task.assignees.map(assignee => (
                  <span key={assignee.id} className="assignee-badge">
                    {assignee.first_name || assignee.username}
                  </span>
                ))
              ) : (
                <span className="assignee-badge unassigned">Не назначено</span>
              )}
            </div>

            <div className="task-info">
              <span className={`task-status status-${task.status}`}>
                {getStatusText(task.status)}
              </span>
              {task.due_date && (
                <span className="task-deadline">
                  {formatRelativeTime(task.due_date)}
                </span>
              )}
            </div>
          </div>

          <div className="task-footer">
            {task.creator && (
              <span className="task-creator">
                Создал: {task.creator.first_name || task.creator.username}
              </span>
            )}
            {task.created_at && (
              <span className="task-created">
                {formatTimeAgo(task.created_at)}
              </span>
            )}
          </div>

          {task.category && (
            <div className="task-category">
              <span className="category-badge">{task.category.name}</span>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export function StatsWidget({ stats }) {
  if (!stats) return null

  return (
    <div className="stats-widget">
      <div className="stat-card">
        <div className="stat-value">{stats.total_tasks}</div>
        <div className="stat-label">Всего задач</div>
      </div>

      <div className="stat-card stat-pending">
        <div className="stat-value">{stats.pending_tasks}</div>
        <div className="stat-label">Ожидает</div>
      </div>

      <div className="stat-card stat-in-progress">
        <div className="stat-value">{stats.in_progress_tasks}</div>
        <div className="stat-label">В работе</div>
      </div>

      <div className="stat-card stat-completed">
        <div className="stat-value">{stats.completed_tasks}</div>
        <div className="stat-label">Выполнено</div>
      </div>
    </div>
  )
}

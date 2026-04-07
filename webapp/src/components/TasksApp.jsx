import { useState, useEffect } from 'react'
import { getTasks, getStats, getCategories } from '../services/api'
import { TaskList } from './TaskList'
import { TaskDetail } from './TaskDetail'
import { StatsWidget } from './StatsWidget'
import { FilterBar } from './FilterBar'
import EmailAccounts from './EmailAccounts'

export function TasksApp({ currentUser }) {
  const initialTab = new URLSearchParams(window.location.search).get('tab') || 'my_tasks'
  const [tasks, setTasks] = useState([])
  const [stats, setStats] = useState(null)
  const [categories, setCategories] = useState([])
  const [selectedTask, setSelectedTask] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState(initialTab)

  const [filters, setFilters] = useState({
    status: null,
    category_id: null
  })

  useEffect(() => {
    if (activeTab !== 'emails') {
      loadData()
    }
  }, [filters, activeTab])

  async function loadData() {
    try {
      setLoading(true)
      setError(null)

      const apiFilters = { ...filters }

      if (activeTab === 'my_tasks') {
        apiFilters.assigned_to = currentUser.id
      } else if (activeTab === 'created_by_me') {
        apiFilters.created_by = currentUser.id
      }

      const statsParams = {}
      if (activeTab === 'my_tasks') {
        statsParams.assigned_to = currentUser.id
      } else if (activeTab === 'created_by_me') {
        statsParams.created_by = currentUser.id
      }

      const [tasksData, statsData, categoriesData] = await Promise.all([
        getTasks(apiFilters),
        getStats(statsParams),
        getCategories()
      ])

      setTasks(tasksData)
      setStats(statsData)
      setCategories(categoriesData)
    } catch (err) {
      console.error('Error loading data:', err)
      setError('Ошибка загрузки данных')
    } finally {
      setLoading(false)
    }
  }

  function handleTaskClick(task) {
    setSelectedTask(task)
  }

  function handleBackToList() {
    setSelectedTask(null)
    loadData()
  }

  function handleFilterChange(newFilters) {
    setFilters({ ...filters, ...newFilters })
  }

  const isCreator = selectedTask && selectedTask.creator && selectedTask.creator.id === currentUser.id

  if (loading && !tasks.length) {
    return (
      <div className="loading-container">
        <div className="loading-spinner"></div>
        <p>Загрузка...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="error-container">
        <h2>Ошибка</h2>
        <p>{error}</p>
        <button onClick={loadData}>Попробовать снова</button>
      </div>
    )
  }

  if (selectedTask) {
    return (
      <TaskDetail
        task={selectedTask}
        onBack={handleBackToList}
        isManager={isCreator}
        currentUserId={currentUser.id}
      />
    )
  }

  return (
    <div className="tasks-app">
      <header className="app-header">
        <h1>Мои задачи</h1>
        <p className="subtitle">Управление задачами</p>
      </header>

      <div className="tabs">
        <button
          className={`tab ${activeTab === 'my_tasks' ? 'active' : ''}`}
          onClick={() => setActiveTab('my_tasks')}
        >
          Мои задачи
        </button>
        <button
          className={`tab ${activeTab === 'created_by_me' ? 'active' : ''}`}
          onClick={() => setActiveTab('created_by_me')}
        >
          Поставленные
        </button>
        <button
          className={`tab ${activeTab === 'emails' ? 'active' : ''}`}
          onClick={() => setActiveTab('emails')}
        >
          Почта
        </button>
      </div>

      {activeTab === 'emails' ? (
        <EmailAccounts currentUser={currentUser} />
      ) : (
        <>
          {stats && <StatsWidget stats={stats} />}

          <FilterBar
            filters={filters}
            categories={categories}
            onFilterChange={handleFilterChange}
          />

          <TaskList
            tasks={tasks}
            onTaskClick={handleTaskClick}
            loading={loading}
          />
        </>
      )}

      {!loading && tasks.length === 0 && activeTab !== 'emails' && (
        <div className="empty-state">
          <p>
            {activeTab === 'my_tasks'
              ? 'У вас пока нет назначенных задач'
              : 'Вы еще не назначали задачи'}
          </p>
        </div>
      )}
    </div>
  )
}

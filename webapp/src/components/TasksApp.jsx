import { useState, useEffect } from 'react'
import { getTasks, getStats, getCategories, getApiUrl } from '../services/api'
import { TaskList } from './TaskList'
import { TaskDetail } from './TaskDetail'
import { StatsWidget } from './StatsWidget'
import { FilterBar } from './FilterBar'
import EmailAccounts from './EmailAccounts'

export function TasksApp({ userId }) {
  const [tasks, setTasks] = useState([])
  const [stats, setStats] = useState(null)
  const [categories, setCategories] = useState([])
  const [selectedTask, setSelectedTask] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState('my_tasks') // my_tasks | created_by_me | emails
  const [currentUser, setCurrentUser] = useState(null)

  // Фильтры
  const [filters, setFilters] = useState({
    status: null,
    category_id: null
  })

  // Загрузка данных пользователя при первом рендере
  useEffect(() => {
    loadUserData()
  }, [])

  useEffect(() => {
    if (activeTab !== 'emails') {
      loadData()
    }
  }, [filters, activeTab])

  async function loadUserData() {
    // Fallback: enough for email APIs, even if /users temporarily fails.
    setCurrentUser({ id: userId })

    try {
      const response = await fetch(getApiUrl(`/users?current_user_id=${userId}`))
      if (response.ok) {
        const users = await response.json()
        const user = users.find(u => u.id === userId)
        if (user) {
          setCurrentUser(user)
        }
      }
    } catch (error) {
      console.error('Error loading user data:', error)
    }
  }

  async function loadData() {
    try {
      setLoading(true)
      setError(null)

      // Формируем фильтры в зависимости от вкладки
      const apiFilters = { ...filters }

      if (activeTab === 'my_tasks') {
        // Вкладка "Мои задачи" - где я исполнитель
        apiFilters.assigned_to = userId
      } else if (activeTab === 'created_by_me') {
        // Вкладка "Назначенные мной" - где я создатель
        apiFilters.created_by = userId
      }

      // Параметры для статистики
      const statsParams = {}
      if (activeTab === 'my_tasks') {
        statsParams.assigned_to = userId
      } else if (activeTab === 'created_by_me') {
        statsParams.created_by = userId
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
    loadData() // Перезагружаем данные
  }

  function handleFilterChange(newFilters) {
    setFilters({ ...filters, ...newFilters })
  }

  // Определяем является ли пользователь создателем выбранной задачи
  const isCreator = selectedTask && selectedTask.creator && selectedTask.creator.id === userId

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
      />
    )
  }

  return (
    <div className="tasks-app">
      <header className="app-header">
        <h1>Мои задачи</h1>
        <p className="subtitle">Управление задачами</p>
      </header>

      {/* Вкладки */}
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
          Назначенные мной
        </button>
        <button
          className={`tab ${activeTab === 'emails' ? 'active' : ''}`}
          onClick={() => setActiveTab('emails')}
        >
          📧 Email
        </button>
      </div>

      {/* Контент в зависимости от вкладки */}
      {activeTab === 'emails' ? (
        <EmailAccounts currentUser={currentUser} />
      ) : (
        <>
          {/* Статистика для обеих вкладок */}
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

      {!loading && tasks.length === 0 && (
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

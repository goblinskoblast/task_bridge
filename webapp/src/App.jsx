import { useEffect, useState } from 'react'
import { TasksApp } from './components/TasksApp'
import { getCurrentUser } from './services/api'
import {
  applyTelegramTheme,
  getTelegramParams,
  prepareTelegramWebApp,
  waitForTelegramInitData,
} from './utils/telegram'

function App() {
  const [currentUser, setCurrentUser] = useState(null)
  const [taskId, setTaskId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let isMounted = true

    const bootstrap = async () => {
      const params = getTelegramParams()
      setTaskId(params.task_id ? parseInt(params.task_id, 10) : null)

      const tg = prepareTelegramWebApp()
      applyTelegramTheme(tg)
      await waitForTelegramInitData()

      try {
        const user = await getCurrentUser()
        if (isMounted) {
          setCurrentUser(user)
        }
      } catch (err) {
        console.error('Failed to load authenticated user:', err)
        if (isMounted) {
          setError('Не удалось подтвердить пользователя')
        }
      } finally {
        if (isMounted) {
          setLoading(false)
        }
      }
    }

    bootstrap()

    return () => {
      isMounted = false
    }
  }, [])

  if (loading) {
    return (
      <div className="loading-container">
        <div className="loading-spinner"></div>
        <p>Загрузка...</p>
      </div>
    )
  }

  if (!currentUser) {
    return (
      <div className="error-container">
        <h2>Ошибка</h2>
        <p>{error || 'Не удалось определить пользователя'}</p>
      </div>
    )
  }

  return (
    <div className="app">
      <TasksApp currentUser={currentUser} taskId={taskId} />
    </div>
  )
}

export default App

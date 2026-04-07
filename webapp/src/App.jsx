import { useEffect, useState } from 'react'
import { TasksApp } from './components/TasksApp'
import { getCurrentUser } from './services/api'
import {
  applyTelegramTheme,
  getTelegramParams,
  prepareTelegramWebApp,
  waitForTelegramInitData,
} from './utils/telegram'

const AUTH_RETRY_DELAYS_MS = [0, 600, 1200, 2000]

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

      try {
        let user = null

        for (const delayMs of AUTH_RETRY_DELAYS_MS) {
          if (delayMs > 0) {
            await new Promise(resolve => window.setTimeout(resolve, delayMs))
          }

          await waitForTelegramInitData()

          try {
            user = await getCurrentUser()
            break
          } catch (attemptError) {
            const status = attemptError?.response?.status
            if (status !== 401) {
              throw attemptError
            }
          }
        }

        if (!user) {
          throw new Error('AUTH_RETRY_EXHAUSTED')
        }

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

import { useEffect, useState } from 'react'
import { TasksApp } from './components/TasksApp'
import { getTelegramParams } from './utils/telegram'

function App() {
  const [userId, setUserId] = useState(null)
  const [taskId, setTaskId] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const params = getTelegramParams()

    setUserId(params.user_id ? parseInt(params.user_id, 10) : null)
    setTaskId(params.task_id ? parseInt(params.task_id, 10) : null)
    setLoading(false)

    if (window.Telegram?.WebApp) {
      const tg = window.Telegram.WebApp
      tg.ready()
      tg.expand()

      document.documentElement.style.setProperty('--tg-theme-bg-color', tg.themeParams.bg_color || '#ffffff')
      document.documentElement.style.setProperty('--tg-theme-text-color', tg.themeParams.text_color || '#000000')
      document.documentElement.style.setProperty('--tg-theme-hint-color', tg.themeParams.hint_color || '#999999')
      document.documentElement.style.setProperty('--tg-theme-link-color', tg.themeParams.link_color || '#2481cc')
      document.documentElement.style.setProperty('--tg-theme-button-color', tg.themeParams.button_color || '#2481cc')
      document.documentElement.style.setProperty('--tg-theme-button-text-color', tg.themeParams.button_text_color || '#ffffff')
      document.documentElement.style.setProperty('--tg-theme-secondary-bg-color', tg.themeParams.secondary_bg_color || '#f4f4f5')

      if (tg.colorScheme === 'dark') {
        document.body.classList.add('dark-theme')
      } else {
        document.body.classList.remove('dark-theme')
      }
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

  if (!userId) {
    return (
      <div className="error-container">
        <h2>Ошибка</h2>
        <p>Не удалось определить пользователя</p>
      </div>
    )
  }

  return (
    <div className="app">
      <TasksApp userId={userId} taskId={taskId} />
    </div>
  )
}

export default App

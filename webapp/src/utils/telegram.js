/**
 * Утилиты для работы с Telegram WebApp
 */

export function getTelegramParams() {
  const tg = window.Telegram?.WebApp
  const urlParams = new URLSearchParams(window.location.search)
  const userIdFromUrl = urlParams.get('user_id')
  const storedUserId = window.localStorage.getItem('taskbridge_user_id')

  if (userIdFromUrl) {
    window.localStorage.setItem('taskbridge_user_id', userIdFromUrl)
  }

  return {
    mode: urlParams.get('mode'),
    user_id: userIdFromUrl || storedUserId,
    task_id: urlParams.get('task_id'),
    tab: urlParams.get('tab'),
    telegram_user_id: tg?.initDataUnsafe?.user?.id?.toString() || null
  }
}

export function getTelegramWebApp() {
  return window.Telegram?.WebApp || null
}

export function closeTelegramWebApp() {
  const tg = getTelegramWebApp()
  if (tg) {
    tg.close()
  }
}

export function showTelegramAlert(message) {
  const tg = getTelegramWebApp()
  if (tg) {
    tg.showAlert(message)
  } else {
    alert(message)
  }
}

export function showTelegramConfirm(message, callback) {
  const tg = getTelegramWebApp()
  if (tg) {
    tg.showConfirm(message, callback)
  } else {
    const result = confirm(message)
    callback(result)
  }
}

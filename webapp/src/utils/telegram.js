/**
 * Утилиты для работы с Telegram WebApp
 */

export function getTelegramParams() {
  const urlParams = new URLSearchParams(window.location.search)

  return {
    mode: urlParams.get('mode'),
    user_id: urlParams.get('user_id'),
    task_id: urlParams.get('task_id')
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

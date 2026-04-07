/**
 * Утилиты для работы с Telegram WebApp
 */

export function getTelegramParams() {
  const tg = window.Telegram?.WebApp
  const urlParams = new URLSearchParams(window.location.search)

  return {
    mode: urlParams.get('mode'),
    task_id: urlParams.get('task_id'),
    tab: urlParams.get('tab'),
    telegram_user_id: tg?.initDataUnsafe?.user?.id?.toString() || null,
    init_data: getTelegramInitData()
  }
}

export function getTelegramInitData() {
  const tg = window.Telegram?.WebApp
  const urlParams = new URLSearchParams(window.location.search)
  return tg?.initData || urlParams.get('tg_init_data') || null
}

export function getTelegramAuthHeaders() {
  const initData = getTelegramInitData()
  return initData ? { 'X-Telegram-Init-Data': initData } : {}
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

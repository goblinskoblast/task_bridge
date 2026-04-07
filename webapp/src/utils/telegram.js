/**
 * Утилиты для работы с Telegram WebApp.
 */

function getUrlSearchParams() {
  return new URLSearchParams(window.location.search)
}

export function getWebappAuthToken() {
  const urlParams = getUrlSearchParams()
  return urlParams.get('tb_auth') || null
}

export function getTelegramWebApp() {
  return window.Telegram?.WebApp || null
}

export function prepareTelegramWebApp() {
  const tg = getTelegramWebApp()
  if (!tg) {
    return null
  }

  try {
    tg.ready()
    tg.expand()
  } catch (error) {
    console.warn('Telegram WebApp initialization warning:', error)
  }

  return tg
}

export function applyTelegramTheme(tg = getTelegramWebApp()) {
  if (!tg) {
    document.body.classList.remove('dark-theme')
    return
  }

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

export function getTelegramInitData() {
  const tg = getTelegramWebApp()
  const urlParams = getUrlSearchParams()
  return tg?.initData || urlParams.get('tg_init_data') || null
}

export async function waitForTelegramInitData(timeoutMs = 5000, pollIntervalMs = 100) {
  const startedAt = Date.now()

  while (Date.now() - startedAt < timeoutMs) {
    const initData = getTelegramInitData()
    if (initData) {
      return initData
    }
    await new Promise(resolve => window.setTimeout(resolve, pollIntervalMs))
  }

  return getTelegramInitData()
}

export function getTelegramParams() {
  const tg = getTelegramWebApp()
  const urlParams = getUrlSearchParams()

  return {
    mode: urlParams.get('mode'),
    task_id: urlParams.get('task_id'),
    tab: urlParams.get('tab'),
    telegram_user_id: tg?.initDataUnsafe?.user?.id?.toString() || null,
    init_data: getTelegramInitData(),
  }
}

export function getTelegramAuthHeaders() {
  const initData = getTelegramInitData()
  return initData ? { 'X-Telegram-Init-Data': initData } : {}
}

export function getWebappAuthQueryParams() {
  const params = {}
  const initData = getTelegramInitData()
  const webappAuthToken = getWebappAuthToken()

  if (initData) {
    params.tg_init_data = initData
  }
  if (webappAuthToken) {
    params.tb_auth = webappAuthToken
  }

  return params
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

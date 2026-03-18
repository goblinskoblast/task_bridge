import { useState, useEffect } from 'react'
import { Mail, Plus, Trash2, Check, X, AlertCircle } from 'lucide-react'
import { getApiUrl } from '../services/api'
import '../styles/EmailAccounts.css'

export default function EmailAccounts({ currentUser }) {
  const [accounts, setAccounts] = useState([])
  const [loading, setLoading] = useState(true)
  const [showAddForm, setShowAddForm] = useState(false)
  const [testing, setTesting] = useState(false)

  // Р¤РѕСЂРјР° РЅРѕРІРѕРіРѕ Р°РєРєР°СѓРЅС‚Р°
  const [newAccount, setNewAccount] = useState({
    email_address: '',
    imap_server: '',
    imap_port: 993,
    imap_username: '',
    imap_password: '',
    use_ssl: true,
    folder: 'INBOX',
    auto_confirm: false
  })

  // IMAP servers РґР»СЏ Р°РІС‚РѕРѕРїСЂРµРґРµР»РµРЅРёСЏ
  const IMAP_SERVERS = {
    'gmail.com': { server: 'imap.gmail.com', port: 993 },
    'outlook.com': { server: 'outlook.office365.com', port: 993 },
    'hotmail.com': { server: 'outlook.office365.com', port: 993 },
    'yandex.ru': { server: 'imap.yandex.ru', port: 993 },
    'yandex.com': { server: 'imap.yandex.com', port: 993 },
    'mail.ru': { server: 'imap.mail.ru', port: 993 },
    'yahoo.com': { server: 'imap.mail.yahoo.com', port: 993 }
  }

  useEffect(() => {
    if (currentUser) {
      loadAccounts()
    } else {
      setLoading(false)
    }
  }, [currentUser])

  // РђРІС‚РѕРѕРїСЂРµРґРµР»РµРЅРёРµ IMAP СЃРµСЂРІРµСЂР° РїРѕ email
  useEffect(() => {
    if (newAccount.email_address) {
      const domain = newAccount.email_address.split('@')[1]?.toLowerCase()
      if (domain && IMAP_SERVERS[domain]) {
        setNewAccount(prev => ({
          ...prev,
          imap_server: IMAP_SERVERS[domain].server,
          imap_port: IMAP_SERVERS[domain].port,
          imap_username: prev.email_address
        }))
      } else if (domain) {
        setNewAccount(prev => ({
          ...prev,
          imap_server: `imap.${domain}`,
          imap_username: prev.email_address
        }))
      }
    }
  }, [newAccount.email_address])

  const loadAccounts = async () => {
    try {
      const response = await fetch(getApiUrl(`/email-accounts?user_id=${currentUser.id}`))
      if (response.ok) {
        const data = await response.json()
        setAccounts(data)
      }
    } catch (error) {
      console.error('Error loading email accounts:', error)
    } finally {
      setLoading(false)
    }
  }

  const connectGoogle = () => {
    if (!currentUser?.id) {
      alert('Пользователь не найден')
      return
    }

    window.location.href = getApiUrl(`/oauth/google/start?user_id=${currentUser.id}`)
  }

  const testConnection = async () => {
    setTesting(true)
    try {
      const response = await fetch(getApiUrl('/email-accounts/test'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email_address: newAccount.email_address,
          imap_server: newAccount.imap_server,
          imap_port: newAccount.imap_port,
          imap_username: newAccount.imap_username,
          imap_password: newAccount.imap_password,
          use_ssl: newAccount.use_ssl
        })
      })

      const result = await response.json()

      if (result.success) {
        alert('вњ… РџРѕРґРєР»СЋС‡РµРЅРёРµ СѓСЃРїРµС€РЅРѕ!')
      } else {
        alert(`вќЊ РћС€РёР±РєР° РїРѕРґРєР»СЋС‡РµРЅРёСЏ:\n${result.message}`)
      }
    } catch (error) {
      alert(`вќЊ РћС€РёР±РєР°: ${error.message}`)
    } finally {
      setTesting(false)
    }
  }

  const createAccount = async () => {
    try {
      const response = await fetch(getApiUrl(`/email-accounts?user_id=${currentUser.id}`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newAccount)
      })

      if (response.ok) {
        alert('вњ… Email Р°РєРєР°СѓРЅС‚ СѓСЃРїРµС€РЅРѕ РґРѕР±Р°РІР»РµРЅ!')
        setShowAddForm(false)
        resetForm()
        loadAccounts()
      } else {
        const error = await response.json()
        alert(`вќЊ РћС€РёР±РєР°: ${error.detail}`)
      }
    } catch (error) {
      alert(`вќЊ РћС€РёР±РєР°: ${error.message}`)
    }
  }

  const toggleActive = async (accountId, currentStatus) => {
    try {
      const response = await fetch(getApiUrl(`/email-accounts/${accountId}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !currentStatus })
      })

      if (response.ok) {
        loadAccounts()
      }
    } catch (error) {
      console.error('Error toggling account:', error)
    }
  }

  const toggleAutoConfirm = async (accountId, currentStatus) => {
    try {
      const response = await fetch(getApiUrl(`/email-accounts/${accountId}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_confirm: !currentStatus })
      })

      if (response.ok) {
        loadAccounts()
      }
    } catch (error) {
      console.error('Error toggling auto-confirm:', error)
    }
  }

  const deleteAccount = async (accountId, email) => {
    if (!confirm(`РЈРґР°Р»РёС‚СЊ Р°РєРєР°СѓРЅС‚ ${email}?`)) return

    try {
      const response = await fetch(getApiUrl(`/email-accounts/${accountId}`), {
        method: 'DELETE'
      })

      if (response.ok) {
        alert('вњ… РђРєРєР°СѓРЅС‚ СѓРґР°Р»РµРЅ')
        loadAccounts()
      }
    } catch (error) {
      alert(`вќЊ РћС€РёР±РєР°: ${error.message}`)
    }
  }

  const resetForm = () => {
    setNewAccount({
      email_address: '',
      imap_server: '',
      imap_port: 993,
      imap_username: '',
      imap_password: '',
      use_ssl: true,
      folder: 'INBOX',
      auto_confirm: false
    })
  }

  const formatTimeAgo = (dateString) => {
    if (!dateString) return 'РћР¶РёРґР°РЅРёРµ РїСЂРѕРІРµСЂРєРё'

    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now - date
    const diffMinutes = Math.floor(diffMs / (1000 * 60))
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

    if (diffMinutes < 1) return 'РўРѕР»СЊРєРѕ С‡С‚Рѕ'
    if (diffMinutes < 60) return `${diffMinutes} РјРёРЅ РЅР°Р·Р°Рґ`
    if (diffHours < 24) return `${diffHours} С‡ РЅР°Р·Р°Рґ`
    if (diffDays === 1) return 'Р’С‡РµСЂР°'
    if (diffDays < 7) return `${diffDays} РґРЅ РЅР°Р·Р°Рґ`

    return `${date.getDate()}.${String(date.getMonth() + 1).padStart(2, '0')}.${date.getFullYear()}`
  }

  if (loading) {
    return (
      <div className="email-accounts-container">
        <div className="loading">Р—Р°РіСЂСѓР·РєР°...</div>
      </div>
    )
  }

  if (!currentUser) {
    return (
      <div className="email-accounts-container">
        <div className="empty-state">
          <AlertCircle size={64} />
          <h3>РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ РЅРµ РЅР°Р№РґРµРЅ</h3>
          <p>РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РіСЂСѓР·РёС‚СЊ РґР°РЅРЅС‹Рµ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ. РџРѕРїСЂРѕР±СѓР№С‚Рµ РїРµСЂРµР·Р°РіСЂСѓР·РёС‚СЊ СЃС‚СЂР°РЅРёС†Сѓ.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="email-accounts-container">
      <div className="email-accounts-header">
        <h1>
          <Mail size={28} />
          Email РђРєРєР°СѓРЅС‚С‹
        </h1>
        <button
          className="btn-primary"
          onClick={connectGoogle}
          disabled={accounts.length >= 5}
        >
          📩 Подключить Gmail
        </button>
        <button
          className="btn-primary"
          onClick={() => setShowAddForm(true)}
          disabled={accounts.length >= 5}
        >
          <Plus size={18} />
          Добавить Email
        </button>
      </div>

      {accounts.length >= 5 && (
        <div className="info-message">
          <AlertCircle size={18} />
          Р”РѕСЃС‚РёРіРЅСѓС‚ Р»РёРјРёС‚: 5 email Р°РєРєР°СѓРЅС‚РѕРІ
        </div>
      )}

      {showAddForm && (
        <div className="modal-overlay" onClick={() => setShowAddForm(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <h2>Р”РѕР±Р°РІРёС‚СЊ Email РђРєРєР°СѓРЅС‚</h2>

            <div className="form-group">
              <label>Email Р°РґСЂРµСЃ</label>
              <input
                type="email"
                value={newAccount.email_address}
                onChange={e => setNewAccount({ ...newAccount, email_address: e.target.value })}
                placeholder="example@gmail.com"
              />
            </div>

            <div className="form-row">
              <div className="form-group">
                <label>IMAP РЎРµСЂРІРµСЂ</label>
                <input
                  type="text"
                  value={newAccount.imap_server}
                  onChange={e => setNewAccount({ ...newAccount, imap_server: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label>РџРѕСЂС‚</label>
                <input
                  type="number"
                  value={newAccount.imap_port}
                  onChange={e => setNewAccount({ ...newAccount, imap_port: parseInt(e.target.value) })}
                />
              </div>
            </div>

            <div className="form-group">
              <label>РџР°СЂРѕР»СЊ РїСЂРёР»РѕР¶РµРЅРёСЏ</label>
              <input
                type="password"
                value={newAccount.imap_password}
                onChange={e => setNewAccount({ ...newAccount, imap_password: e.target.value })}
                placeholder="App Password"
              />
            </div>

            <div className="form-group">
              <label>
                <input
                  type="checkbox"
                  checked={newAccount.auto_confirm}
                  onChange={e => setNewAccount({ ...newAccount, auto_confirm: e.target.checked })}
                />
                РђРІС‚РѕРїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ Р·Р°РґР°С‡
              </label>
            </div>

            <div className="modal-actions">
              <button className="btn-secondary" onClick={testConnection} disabled={testing}>
                {testing ? 'РўРµСЃС‚РёСЂРѕРІР°РЅРёРµ...' : 'РўРµСЃС‚ РїРѕРґРєР»СЋС‡РµРЅРёСЏ'}
              </button>
              <button className="btn-primary" onClick={createAccount}>
                Р”РѕР±Р°РІРёС‚СЊ
              </button>
              <button className="btn-secondary" onClick={() => { setShowAddForm(false); resetForm(); }}>
                РћС‚РјРµРЅР°
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="email-accounts-list">
        {accounts.map(account => (
          <div key={account.id} className="email-account-card">
            <div className="account-header">
              <div className="account-info">
                <h3>{account.email_address}</h3>
                <span className="account-server">{account.imap_server}:{account.imap_port}</span>
              </div>

              <div className="account-actions">
                <button
                  className={`btn-toggle ${account.is_active ? 'active' : 'inactive'}`}
                  onClick={() => toggleActive(account.id, account.is_active)}
                  title={account.is_active ? 'РџСЂРёРѕСЃС‚Р°РЅРѕРІРёС‚СЊ' : 'РђРєС‚РёРІРёСЂРѕРІР°С‚СЊ'}
                >
                  {account.is_active ? <Check size={16} /> : <X size={16} />}
                  {account.is_active ? 'РђРєС‚РёРІРµРЅ' : 'РџСЂРёРѕСЃС‚Р°РЅРѕРІР»РµРЅ'}
                </button>

                <button
                  className="btn-icon btn-danger"
                  onClick={() => deleteAccount(account.id, account.email_address)}
                  title="РЈРґР°Р»РёС‚СЊ"
                >
                  <Trash2 size={18} />
                </button>
              </div>
            </div>

            <div className="account-stats">
              <div className="stat">
                <span className="stat-label">РџРѕСЃР»РµРґРЅСЏСЏ РїСЂРѕРІРµСЂРєР°:</span>
                <span className="stat-value">{formatTimeAgo(account.last_checked)}</span>
              </div>
              <div className="stat">
                <span className="stat-label">РћР±СЂР°Р±РѕС‚Р°РЅРѕ РїРёСЃРµРј:</span>
                <span className="stat-value">{account.stats.processed_messages}</span>
              </div>
              <div className="stat">
                <span className="stat-label">РЎРѕР·РґР°РЅРѕ Р·Р°РґР°С‡:</span>
                <span className="stat-value">{account.stats.tasks_created}</span>
              </div>
              <div className="stat">
                <span className="stat-label">РђРІС‚РѕРїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ:</span>
                <button
                  className={`btn-toggle-small ${account.auto_confirm ? 'on' : 'off'}`}
                  onClick={() => toggleAutoConfirm(account.id, account.auto_confirm)}
                >
                  {account.auto_confirm ? 'Р’РєР»' : 'Р’С‹РєР»'}
                </button>
              </div>
            </div>

          </div>
        ))}

        {accounts.length === 0 && (
          <div className="empty-state">
            <Mail size={64} />
            <h3>Email Р°РєРєР°СѓРЅС‚С‹ РЅРµ РЅР°Р№РґРµРЅС‹</h3>
            <p>Р”РѕР±Р°РІСЊС‚Рµ email Р°РєРєР°СѓРЅС‚ РґР»СЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРѕРіРѕ СЃРѕР·РґР°РЅРёСЏ Р·Р°РґР°С‡ РёР· РїРёСЃРµРј</p>
            <button className="btn-primary" onClick={() => setShowAddForm(true)}>
              <Plus size={18} />
              Р”РѕР±Р°РІРёС‚СЊ РїРµСЂРІС‹Р№ Email
            </button>
          </div>
        )}
      </div>
    </div>
  )
}




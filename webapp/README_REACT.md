# TaskBridge WebApp

Современное веб-приложение на React для управления задачами через Telegram WebApp.

**Важно:** Это единственное веб-приложение в проекте. Старые версии на ванильном JS удалены. Используется только React с современным дизайном.

## Установка и запуск

### 1. Установка зависимостей

```bash
cd webapp
npm install
```

### 2. Режимы запуска

#### Development режим (с hot reload)
```bash
npm run dev
```
Приложение будет доступно на `http://localhost:5173`

#### Production сборка
```bash
npm run build
```
Собранные файлы будут в папке `dist/`

#### Preview production сборки
```bash
npm run preview
```

## Структура проекта

```
webapp/
├── src/
│   ├── components/          # React компоненты
│   │   ├── ManagerMode.jsx  # Режим менеджера
│   │   ├── ExecutorMode.jsx # Режим исполнителя
│   │   ├── TaskList.jsx     # Список задач
│   │   ├── TaskDetail.jsx   # Детали задачи
│   │   ├── FilterBar.jsx    # Панель фильтров
│   │   └── StatsWidget.jsx  # Виджет статистики
│   ├── services/
│   │   └── api.js           # API клиент
│   ├── utils/
│   │   ├── format.js        # Утилиты форматирования
│   │   └── telegram.js      # Telegram WebApp утилиты
│   ├── styles/
│   │   └── main.css         # Основные стили
│   ├── App.jsx              # Главный компонент
│   └── main.jsx             # Точка входа
├── index.html               # HTML шаблон
├── vite.config.js           # Конфигурация Vite
└── package.json             # Зависимости проекта
```

## Основные возможности

### Режим менеджера
- Просмотр всех созданных задач
- Фильтрация по статусу и категории
- Добавление/удаление исполнителей
- Просмотр статистики
- Изменение статусов задач

### Режим исполнителя
- Просмотр назначенных задач
- Вкладки "Мои задачи" и "Все задачи"
- Изменение статусов задач
- Добавление комментариев

### Общие возможности
- Просмотр деталей задачи
- Комментарии с уведомлениями
- Просмотр файлов
- Интеграция с Telegram темами
- Адаптивный дизайн

## Уведомления

При добавлении исполнителя через WebApp, ему автоматически отправляется уведомление в Telegram с информацией о задаче.

## API Integration

Приложение взаимодействует с FastAPI бэкендом через следующие endpoints:

- `GET /api/tasks` - список задач
- `GET /api/tasks/{id}` - детали задачи
- `PATCH /api/tasks/{id}/status` - изменение статуса
- `GET/POST /api/tasks/{id}/comments` - комментарии
- `POST /api/tasks/{id}/assignees` - добавление исполнителя
- `DELETE /api/tasks/{id}/assignees/{user_id}` - удаление исполнителя
- `GET /api/categories` - категории
- `GET /api/users` - пользователи
- `GET /api/stats` - статистика

## Development

### Proxy настройка

В `vite.config.js` настроен proxy для API запросов:

```javascript
proxy: {
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true
  }
}
```

В development режиме все запросы к `/api` будут перенаправлены на FastAPI сервер.

### Telegram WebApp параметры

Приложение получает параметры через URL:
- `mode` - режим работы (manager/executor)
- `user_id` - ID пользователя
- `task_id` - ID задачи (опционально, для прямого открытия)

Пример: `?mode=manager&user_id=123`

## Deployment

### 1. Production сборка
```bash
npm run build
```

### 2. Настройка FastAPI для раздачи статики

В `app.py` уже настроена раздача статических файлов из папки `dist/`:

```python
app.mount("/static", StaticFiles(directory="webapp/dist/assets"), name="static")

@app.get("/")
async def read_root():
    return FileResponse("webapp/dist/index.html")
```

### 3. Запуск production сервера

```bash
cd ..
uvicorn webapp.app:app --host 0.0.0.0 --port 8000
```

## Дизайн

Приложение использует:
- CSS переменные для темизации
- Градиентные фоны
- Плавные анимации и transitions
- Адаптивную сетку (Grid/Flexbox)
- Интеграцию с цветовой схемой Telegram

Основные цвета:
- Primary: `#2481cc`
- Success: `#198754`
- Warning: `#ffc107`
- Danger: `#dc3545`
- Info: `#0dcaf0`

## Troubleshooting

### Ошибка CORS
Убедитесь, что FastAPI запущен и настроен правильный proxy в `vite.config.js`

### Не загружаются данные
Проверьте, что:
1. FastAPI сервер запущен на порту 8000
2. База данных инициализирована
3. Переданы правильные параметры `user_id` и `mode`

### Не приходят уведомления
Проверьте:
1. Telegram бот запущен
2. Пользователи авторизованы в боте
3. Логи в `webapp/app.py` для ошибок отправки

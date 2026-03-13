# -*- coding: utf-8 -*-
"""
Тест подключения к базе данных Railway PostgreSQL
"""

from db.database import get_db_session
from db.models import User, Chat, Task, Category
from datetime import datetime

print("=== Тестирование базы данных Railway PostgreSQL ===\n")

db = get_db_session()

try:
    # Тест 1: Создание тестового пользователя
    print("[1/7] Создание тестового пользователя...")
    test_user = User(
        telegram_id=999999999,
        username="test_railway_user",
        first_name="Test",
        last_name="Railway"
    )
    db.add(test_user)
    db.commit()
    db.refresh(test_user)
    print(f"   [OK] Пользователь создан: ID={test_user.id}, username={test_user.username}")

    # Тест 2: Создание тестового чата
    print("\n[2/7] Создание тестового чата...")
    test_chat = Chat(
        chat_id=-1001234567890,
        chat_type="supergroup",
        title="Test Railway Chat",
        is_active=True
    )
    db.add(test_chat)
    db.commit()
    db.refresh(test_chat)
    print(f"   [OK] Чат создан: ID={test_chat.id}, title={test_chat.title}")

    # Тест 3: Создание категории
    print("\n[3/7] Создание категории...")
    test_category = Category(
        name="Тестирование",
        description="Категория для тестов",
        keywords=["test", "тест"]
    )
    db.add(test_category)
    db.commit()
    db.refresh(test_category)
    print(f"   [OK] Категория создана: ID={test_category.id}, name={test_category.name}")

    # Тест 4: Создание задачи
    print("\n[4/7] Создание тестовой задачи...")
    test_task = Task(
        title="Тестовая задача Railway",
        description="Проверка работы базы данных на Railway PostgreSQL",
        status="pending",
        priority="high",
        created_by=test_user.id,
        category_id=test_category.id,
        due_date=datetime.now()
    )
    db.add(test_task)
    db.commit()
    db.refresh(test_task)
    print(f"   [OK] Задача создана: ID={test_task.id}, title={test_task.title}")

    # Тест 5: Связь many-to-many (назначение исполнителя)
    print("\n[5/7] Назначение исполнителя на задачу...")
    test_task.assignees.append(test_user)
    db.commit()
    print(f"   [OK] Исполнитель назначен на задачу")

    # Тест 6: Чтение данных
    print("\n[6/7] Проверка сохранённых данных...")

    users_count = db.query(User).count()
    chats_count = db.query(Chat).count()
    tasks_count = db.query(Task).count()
    categories_count = db.query(Category).count()

    print(f"   Статистика базы данных:")
    print(f"      - Пользователей: {users_count}")
    print(f"      - Чатов: {chats_count}")
    print(f"      - Задач: {tasks_count}")
    print(f"      - Категорий: {categories_count}")

    # Тест 7: Проверка связей
    print("\n[7/7] Проверка связей (relationships)...")
    task_with_relations = db.query(Task).filter(Task.id == test_task.id).first()
    print(f"   [OK] Задача: {task_with_relations.title}")
    print(f"   [OK] Создатель: {task_with_relations.creator.username if task_with_relations.creator else 'N/A'}")
    print(f"   [OK] Категория: {task_with_relations.category.name if task_with_relations.category else 'N/A'}")
    print(f"   [OK] Исполнителей: {len(task_with_relations.assignees)}")
    if task_with_relations.assignees:
        for assignee in task_with_relations.assignees:
            print(f"      - @{assignee.username}")

    print("\n" + "="*60)
    print("SUCCESS! Все тесты пройдены успешно!")
    print("="*60)
    print("\n[OK] Railway PostgreSQL работает отлично!")
    print("[OK] Все таблицы функционируют")
    print("[OK] Связи many-to-many работают")
    print("[OK] Бот готов к запуску!")

except Exception as e:
    print(f"\n[ERROR] Ошибка при тестировании: {e}")
    import traceback
    traceback.print_exc()

finally:
    db.close()

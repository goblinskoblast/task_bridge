# -*- coding: utf-8 -*-
"""
Пересоздание таблиц в базе данных с исправленными типами
"""

from db.database import sync_engine
from db.models import Base

print("=== Пересоздание таблиц в Railway PostgreSQL ===\n")

try:
    print("[1/2] Удаление существующих таблиц...")
    Base.metadata.drop_all(bind=sync_engine)
    print("   [OK] Таблицы удалены")

    print("\n[2/2] Создание таблиц с исправленными типами...")
    Base.metadata.create_all(bind=sync_engine)
    print("   [OK] Таблицы созданы")

    print("\n" + "="*60)
    print("SUCCESS! Таблицы успешно пересозданы!")
    print("="*60)
    print("\n[OK] Все Telegram ID теперь используют BigInteger")
    print("[OK] База данных готова к работе")

except Exception as e:
    print(f"\n[ERROR] Ошибка: {e}")
    import traceback
    traceback.print_exc()

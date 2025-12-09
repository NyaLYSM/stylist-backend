"""
Скрипт инициализации БД - выполняется при старте приложения
Безопасно пересоздает таблицы только если структура изменилась
"""
import os
from sqlalchemy import create_engine, inspect
from database import Base, DATABASE_URL
import models

def init_database():
    """Инициализирует/обновляет структуру БД"""
    engine = create_engine(DATABASE_URL)
    inspector = inspect(engine)
    
    # Проверяем существующие таблицы
    existing_tables = inspector.get_table_names()
    
    print("🔍 Проверка структуры БД...")
    
    # Если таблица wardrobe существует, проверяем её структуру
    if 'wardrobe' in existing_tables:
        columns = [col['name'] for col in inspector.get_columns('wardrobe')]
        print(f"📋 Существующие колонки wardrobe: {columns}")
        
        # Если нет колонки 'name' - нужна пересборка
        if 'name' not in columns:
            print("⚠️  Обнаружена старая структура БД. Пересоздание таблиц...")
            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)
            print("✅ Таблицы успешно пересозданы!")
        else:
            print("✅ Структура БД актуальна")
    else:
        # Таблиц нет - создаём с нуля
        print("🆕 Создание новых таблиц...")
        Base.metadata.create_all(bind=engine)
        print("✅ Таблицы созданы!")

if __name__ == "__main__":
    init_database()

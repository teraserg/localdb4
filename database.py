import os
import shutil
import sqlite3

# Визначаємо шляхи для збереження даних поруч із кодом
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "app_data")
ATTACHMENTS_DIR = os.path.join(DATA_DIR, "attachments")
DB_PATH = os.path.join(DATA_DIR, "hr_system.db")

def init_db():
    """Ініціалізація папок та бази даних"""
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Створюємо таблицю особових справ
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            position TEXT,
            photo_path TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_employee(name, position, source_photo_path=None):
    """Додавання співробітника та копіювання його фото у внутрішнє сховище"""
    final_photo_path = ""
    
    if source_photo_path and os.path.exists(source_photo_path):
        # Отримуємо розширення файлу (наприклад, .jpg)
        file_ext = os.path.splitext(source_photo_path)[1]
        # Формуємо безпечне унікальне ім'я файлу
        safe_name = name.replace(" ", "_").lower()
        new_filename = f"{safe_name}{file_ext}"
        dest_path = os.path.join(ATTACHMENTS_DIR, new_filename)
        
        # Копіюємо файл у нашу папку attachments
        shutil.copy(source_photo_path, dest_path)
        # Зберігаємо відносний шлях, щоб програма працювала, навіть якщо її перенести
        final_photo_path = os.path.join("app_data", "attachments", new_filename)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO employees (full_name, position, photo_path) VALUES (?, ?, ?)",
        (name, position, final_photo_path)
    )
    conn.commit()
    conn.close()

def get_all_employees():
    """Отримання списку всіх особових справ"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, full_name, position, photo_path FROM employees")
    rows = cursor.fetchall()
    conn.close()
    return rows

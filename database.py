import os
import shutil
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "app_data")
ATTACHMENTS_DIR = os.path.join(DATA_DIR, "attachments")
DB_PATH = os.path.join(DATA_DIR, "hr_system.db")

def init_db():
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
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

def _save_photo(name, source_photo_path):
    """Внутрішня функція для копіювання фото"""
    if source_photo_path and os.path.exists(source_photo_path):
        file_ext = os.path.splitext(source_photo_path)[1]
        safe_name = name.replace(" ", "_").lower()
        # Додаємо timestamp або унікальний суфікс, щоб уникнути конфліктів імен при заміні фото
        import time
        new_filename = f"{safe_name}_{int(time.time())}{file_ext}"
        dest_path = os.path.join(ATTACHMENTS_DIR, new_filename)
        
        shutil.copy(source_photo_path, dest_path)
        return os.path.join("app_data", "attachments", new_filename)
    return ""

def add_employee(name, position, source_photo_path=None):
    final_photo_path = _save_photo(name, source_photo_path)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO employees (full_name, position, photo_path) VALUES (?, ?, ?)",
        (name, position, final_photo_path)
    )
    conn.commit()
    conn.close()

def update_employee(emp_id, name, position, source_photo_path=None, keep_old_photo=True):
    """Оновлення існуючої картки за її ID"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if keep_old_photo:
        # Редагуємо лише текст
        cursor.execute(
            "UPDATE employees SET full_name = ?, position = ? WHERE id = ?",
            (name, position, emp_id)
        )
    else:
        # Користувач обрав нове фото (або видалив старе)
        final_photo_path = _save_photo(name, source_photo_path)
        cursor.execute(
            "UPDATE employees SET full_name = ?, position = ?, photo_path = ? WHERE id = ?",
            (name, position, final_photo_path, emp_id)
        )
        
    conn.commit()
    conn.close()

def get_all_employees():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, full_name, position, photo_path FROM employees")
    rows = cursor.fetchall()
    conn.close()
    return rows

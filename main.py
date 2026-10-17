import sys
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLineEdit, QPushButton, QListWidget, 
                             QLabel, QFileDialog, QMessageBox)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt
import database as db

class HRApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Система особових справ (PyQt6 + SQLite)")
        self.setGeometry(100, 100, 700, 450)
        
        # Змінна для зберігання тимчасового шляху до обраного фото
        self.selected_photo_path = None
        
        # Ініціалізуємо базу даних
        db.init_db()
        
        # Головний віджет та лейаут
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        
        # --- ЛІВА ПАНЕЛЬ: Список особових справ ---
        left_layout = QVBoxLayout()
        self.employee_list = QListWidget()
        self.employee_list.itemClicked.connect(self.load_employee_details)
        left_layout.addWidget(QLabel("Список співробітників:"))
        left_layout.addWidget(self.employee_list)
        main_layout.addLayout(left_layout, stretch=2)
        
        # --- ПРАВА ПАНЕЛЬ: Форма додавання / Перегляду ---
        right_layout = QVBoxLayout()
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("ПІБ співробітника")
        
        self.position_input = QLineEdit()
        self.position_input.setPlaceholderText("Посада")
        
        self.btn_select_photo = QPushButton("Обрати фото/скан")
        self.btn_select_photo.clicked.connect(self.select_photo)
        
        self.btn_save = QPushButton("Зберегти особову справу")
        self.btn_save.setStyleSheet("background-color: #2b78e4; color: white; font-weight: bold;")
        self.btn_save.clicked.connect(self.save_employee)
        
        # Вікно попереднього перегляду фотографії
        self.photo_preview = QLabel("Немає фото")
        self.photo_preview.setFixedSize(150, 150)
        self.photo_preview.setStyleSheet("border: 1px solid gray; background-color: #f0f0f0;")
        self.photo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Додаємо елементи на праву панель
        right_layout.addWidget(QLabel("Картка / Нова справа:"))
        right_layout.addWidget(self.name_input)
        right_layout.addWidget(self.position_input)
        right_layout.addWidget(self.btn_select_photo)
        right_layout.addWidget(self.photo_preview)
        right_layout.addWidget(self.btn_save)
        right_layout.addStretch()
        
        main_layout.addLayout(right_layout, stretch=1)
        
        # Оновлюємо список при старті програми
        self.refresh_list()

    def select_photo(self):
        """Відкриває діалогове вікно ОС для вибору файлу зображення"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Оберіть фотографію", "", "Images (*.png *.jpg *.jpeg)"
        )
        if file_path:
            self.selected_photo_path = file_path
            # Показуємо прев'ю обраного фото
            pixmap = QPixmap(file_path)
            self.photo_preview.setPixmap(pixmap.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio))

    def save_employee(self):
        """Зберігає дані в базу та копіює фото"""
        name = self.name_input.text().strip()
        position = self.position_input.text().strip()
        
        if not name:
            QMessageBox.warning(self, "Помилка", "ПІБ є обов'язковим полем!")
            return
            
        db.add_employee(name, position, self.selected_photo_path)
        QMessageBox.information(self, "Успіх", "Особову справу успішно збережено!")
        
        # Очищаємо форму
        self.name_input.clear()
        self.position_input.clear()
        self.photo_preview.setText("Немає фото")
        self.photo_preview.setPixmap(QPixmap())
        self.selected_photo_path = None
        
        self.refresh_list()

    def refresh_list(self):
        """Перезавантажує список співробітників з бази даних"""
        self.employee_list.clear()
        self.employees_data = db.get_all_employees()
        for emp in self.employees_data:
            # Виводимо у список "ПІБ (Посада)"
            self.employee_list.addItem(f"{emp[1]} ({emp[2]})")

    def load_employee_details(self, item):
        """Відображає фото та дані при кліку на людину в списку"""
        index = self.employee_list.row(item)
        emp = self.employees_data[index]
        
        self.name_input.setText(emp[1])
        self.position_input.setText(emp[2])
        
        photo_path = emp[3]
        if photo_path and os.path.exists(photo_path):
            pixmap = QPixmap(photo_path)
            self.photo_preview.setPixmap(pixmap.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio))
        else:
            self.photo_preview.setText("Фото відсутнє")
            self.photo_preview.setPixmap(QPixmap())

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = HRApp()
    window.show()
    sys.exit(app.exec())

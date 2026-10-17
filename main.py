import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import database as db


class HRApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Система особових справ (PyQt6 + SQLite)")
        self.setGeometry(100, 100, 750, 500)
        
        # Стан програми
        self.selected_photo_path = None
        self.current_editing_id = None  # None = Новий користувач, Число = Редагування ID
        self.keep_old_photo = True       # Прапорець: чи змінювалось фото під час редагування
        
        db.init_db()
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        
        # --- ЛІВА ПАНЕЛЬ: Список ---
        left_layout = QVBoxLayout()
        self.employee_list = QListWidget()
        self.employee_list.itemClicked.connect(self.load_employee_details)
        left_layout.addWidget(QLabel("Список співробітників:"))
        left_layout.addWidget(self.employee_list)
        main_layout.addLayout(left_layout, stretch=1)
        
        # --- ПРАВА ПАНЕЛЬ: Картка ---
        right_layout = QVBoxLayout()
        
        self.form_mode_label = QLabel("Створення нової справи")
        self.form_mode_label.setStyleSheet("font-weight: bold; color: green; font-size: 14px;")
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("ПІБ співробітника")
        
        self.position_input = QLineEdit()
        self.position_input.setPlaceholderText("Посада")
        
        self.btn_select_photo = QPushButton("Обрати/Змінити фото")
        self.btn_select_photo.clicked.connect(self.select_photo)
        
        self.photo_preview = QLabel("Немає фото")
        self.photo_preview.setFixedSize(150, 150)
        self.photo_preview.setStyleSheet("border: 1px solid gray; background-color: #f0f0f0;")
        self.photo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Кнопки дій
        self.btn_save = QPushButton("Зберегти особову справу")
        self.btn_save.setStyleSheet("background-color: #2b78e4; color: white; font-weight: bold; font-size: 13px;")
        self.btn_save.clicked.connect(self.save_employee)
        
        self.btn_cancel = QPushButton("Скасувати / Новий профайл")
        self.btn_cancel.clicked.connect(self.reset_form)
        self.btn_cancel.hide()  # Ховаємо кнопку, поки не увімкнено режим редагування
        
        # Пакуємо елементи
        right_layout.addWidget(self.form_mode_label)
        right_layout.addWidget(self.name_input)
        right_layout.addWidget(self.position_input)
        right_layout.addWidget(self.btn_select_photo)
        right_layout.addWidget(self.photo_preview)
        right_layout.addWidget(self.btn_save)
        right_layout.addWidget(self.btn_cancel)
        right_layout.addStretch()
        
        main_layout.addLayout(right_layout, stretch=1)
        
        self.refresh_list()

    def select_photo(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Оберіть фотографію", "", "Images (*.png *.jpg *.jpeg)"
        )
        if file_path:
            self.selected_photo_path = file_path
            self.keep_old_photo = False  # Фотографія була змінена користувачем
            pixmap = QPixmap(file_path)
            self.photo_preview.setPixmap(pixmap.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio))

    def save_employee(self):
        name = self.name_input.text().strip()
        position = self.position_input.text().strip()
        
        if not name:
            QMessageBox.warning(self, "Помилка", "ПІБ є обов'язковим полем!")
            return
            
        if self.current_editing_id is None:
            # РЕЖИМ: Створення нового запису
            db.add_employee(name, position, self.selected_photo_path)
            QMessageBox.information(self, "Успіх", "Особову справу успішно створено!")
        else:
            # РЕЖИМ: Редагування існуючого
            db.update_employee(
                self.current_editing_id, 
                name, 
                position, 
                self.selected_photo_path, 
                self.keep_old_photo
            )
            QMessageBox.information(self, "Успіх", "Дані профайлу оновлено!")
        
        self.reset_form()
        self.refresh_list()

    def load_employee_details(self, item):
        """Викликається при кліку на людину зі списку"""
        index = self.employee_list.row(item)
        emp = self.employees_data[index]
        
        # Перемикаємо стан форми в Редагування
        self.current_editing_id = emp[0] # ID з бази даних
        self.keep_old_photo = True       # За замовчуванням фото не чіпаємо, якщо користувач не обере нове
        
        self.form_mode_label.setText(f"Редагування профайлу (ID: {self.current_editing_id})")
        self.form_mode_label.setStyleSheet("font-weight: bold; color: #cc6600; font-size: 14px;")
        self.btn_save.setText("Оновити дані")
        self.btn_cancel.show()  # Показуємо кнопку скасування
        
        # Заповнюємо текстові поля
        self.name_input.setText(emp[1])
        self.position_input.setText(emp[2])
        
        # Відображаємо фото
        photo_path = emp[3]
        if photo_path and os.path.exists(photo_path):
            pixmap = QPixmap(photo_path)
            self.photo_preview.setPixmap(pixmap.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio))
        else:
            self.photo_preview.setText("Фото відсутнє")
            self.photo_preview.setPixmap(QPixmap())

    def reset_form(self):
        """Повертає форму до початкового стану (Режим Створення)"""
        self.current_editing_id = None
        self.selected_photo_path = None
        self.keep_old_photo = True
        
        self.form_mode_label.setText("Створення нової справи")
        self.form_mode_label.setStyleSheet("font-weight: bold; color: green; font-size: 14px;")
        self.btn_save.setText("Зберегти особову справу")
        self.btn_cancel.hide()
        
        self.name_input.clear()
        self.position_input.clear()
        self.photo_preview.setText("Немає фото")
        self.photo_preview.setPixmap(QPixmap())
        self.employee_list.clearSelection()

    def refresh_list(self):
        self.employee_list.clear()
        self.employees_data = db.get_all_employees()
        for emp in self.employees_data:
            self.employee_list.addItem(f"{emp[1]} ({emp[2]})")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = HRApp()
    window.show()
    sys.exit(app.exec())

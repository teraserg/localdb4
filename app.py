"""Облік особових справ — десктопна аплікація (PyQt6 + SQLite).

Встановлення:  pip install PyQt6
Запуск:        python app_pyqt6.py

Потрібні db.py і paths.py з цієї ж папки. Усі дані програми лежать у папці
app_data поруч із програмою (база, резервні копії, експорт, тимчасові файли).
Стара база personnel.db, що лежить поруч із програмою, при першому запуску
переноситься в app_data; за потреби вона також оновлюється до нової схеми
(UUID, підрозділи, командири) зі збереженням копії в app_data/backups.
"""
import csv
import mimetypes
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    QBuffer,
    QByteArray,
    QDate,
    QIODevice,
    QSettings,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    QUrl,
)
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QDesktopServices,
    QImageReader,
    QKeySequence,
    QPalette,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import paths
from db import PERSON_FIELDS, Database, fmt_date

RANKS = [
    "", "Солдат", "Старший солдат", "Молодший сержант", "Сержант",
    "Старший сержант", "Головний сержант", "Штаб-сержант", "Майстер-сержант",
    "Старший майстер-сержант", "Головний майстер-сержант",
    "Молодший лейтенант", "Лейтенант", "Старший лейтенант", "Капітан",
    "Майор", "Підполковник", "Полковник",
    "Бригадний генерал", "Генерал-майор", "Генерал-лейтенант", "Генерал",
]
STATUSES = ["", "У строю", "У відпустці", "На лікуванні", "У відрядженні",
            "Звільнений", "Інше"]
EVENT_TYPES = ["Призначення", "Присвоєння звання", "Нагорода", "Стягнення",
               "Відпустка", "Лікування", "Відрядження", "Переведення", "Інше"]

# (ключ, підпис, тип віджета, значення для списку)
FORM_FIELDS = [
    ("last_name", "Прізвище *", "line", None),
    ("first_name", "Ім'я *", "line", None),
    ("middle_name", "По батькові", "line", None),
    ("birth_date", "Дата народження", "date", None),
    ("personal_number", "Особовий номер", "line", None),
    ("rank", "Військове звання", "combo", RANKS),
    ("position", "Посада", "line", None),
    ("unit_id", "Підрозділ", "unit", None),
    ("commander_id", "Безпосередній командир", "person", None),
    ("status", "Статус", "combo", STATUSES),
    ("location", "Місце перебування", "line", None),
    ("enlist_date", "Дата призову / початку служби", "date", None),
    ("phone", "Телефон", "line", None),
    ("address", "Адреса проживання", "text", None),
    ("education", "Освіта", "text", None),
    ("family", "Сімейний стан, близькі родичі", "text", None),
    ("notes", "Примітки", "text", None),
]

DATE_FIELDS = {"birth_date", "enlist_date"}
EMPTY_DATE = QDate(1900, 1, 1)  # мінімальна дата = «не вказано»

EXPORT_KEYS = [
    "id", "last_name", "first_name", "middle_name", "birth_date", "personal_number",
    "rank", "position", "unit_name", "status", "location", "enlist_date", "phone", "address",
    "education", "family", "commander_name", "notes", "unit_id", "commander_id",
]


PHOTO_W, PHOTO_H = 150, 200            # розмір фото в картці
PHOTO_MAX_W, PHOTO_MAX_H = 900, 1200   # більші фото зменшуються перед збереженням
MAX_DOC_BYTES = 25 * 1024 * 1024       # ліміт розміру одного скану
DOC_TYPES = ["Паспорт", "ІПН", "Військовий квиток", "Посвідчення", "Диплом / освіта",
             "Медичний документ", "Наказ", "Рапорт", "Інше"]

_TEMP_DIRS = []


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} Б"
    if n < 1024 ** 2:
        return f"{n / 1024:.0f} КБ"
    return f"{n / 1024 ** 2:.1f} МБ"


def fmt_datetime(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return value


def open_blob(parent, filename: str, data: bytes):
    """Записує файл у тимчасову папку й відкриває програмою за замовчуванням.
    Тимчасові копії видаляються при закритті програми (cleanup_temp)."""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(filename).name) or "document"
    paths.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    folder = tempfile.mkdtemp(prefix="doc_", dir=paths.TEMP_DIR)
    _TEMP_DIRS.append(folder)
    path = Path(folder) / safe
    path.write_bytes(data)
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
        QMessageBox.warning(parent, "Відкриття файлу",
                            "Не вдалося відкрити файл. Спробуйте «Зберегти як…».")


def cleanup_temp():
    for folder in _TEMP_DIRS:
        shutil.rmtree(folder, ignore_errors=True)
    _TEMP_DIRS.clear()


class _NoWheel:
    """Домішка: колесо миші змінює значення лише коли віджет у фокусі (після кліку
    чи Tab). Інакше подію ігноруємо — вона йде батьківському віджету, і форма просто
    прокручується. Без цього випадні списки й дати змінюються самі, коли курсор
    опиняється над ними під час прокрутки."""

    def _init_wheel_guard(self):
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)   # не брати фокус від колеса

    def wheelEvent(self, event):
        event.ignore()


class SafeComboBox(_NoWheel, QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_wheel_guard()


class SafeDateEdit(_NoWheel, QDateEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_wheel_guard()


class DateField(QWidget):
    """Поле дати з календарем і кнопкою очищення. Порожнє значення = ''."""

    def __init__(self, today=False, parent=None):
        super().__init__(parent)
        self.edit = SafeDateEdit()
        self.edit.setCalendarPopup(True)
        self.edit.setDisplayFormat("dd.MM.yyyy")
        self.edit.setMinimumDate(EMPTY_DATE)
        self.edit.setSpecialValueText("не вказано")
        self.edit.setDate(QDate.currentDate() if today else EMPTY_DATE)
        clear = QToolButton()
        clear.setText("×")
        clear.setToolTip("Очистити дату")
        clear.clicked.connect(lambda: self.edit.setDate(EMPTY_DATE))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.edit, 1)
        lay.addWidget(clear)

    def iso(self) -> str:
        d = self.edit.date()
        return "" if d == EMPTY_DATE else d.toString("yyyy-MM-dd")

    def set_iso(self, value: str):
        d = QDate.fromString(value or "", "yyyy-MM-dd")
        self.edit.setDate(d if d.isValid() else EMPTY_DATE)


class ChoiceBox(SafeComboBox):
    """Вибір зі списку з пошуком під час набору. Значення — id (UUID) або None."""

    NONE_LABEL = "— не вказано —"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        comp = self.completer()
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.lineEdit().setPlaceholderText("Почніть вводити для пошуку")

    def set_choices(self, choices):
        """choices: [(id, підпис), ...]"""
        self.clear()
        self.addItem(self.NONE_LABEL, None)
        for ident, label in choices:
            self.addItem(label, ident)

    def set_value(self, ident):
        idx = self.findData(ident) if ident else 0
        self.setCurrentIndex(max(idx, 0))

    def value(self):
        """id вибраного елемента або None. ValueError, якщо текст не зі списку."""
        text = self.currentText().strip()
        if not text or text == self.NONE_LABEL:
            return None
        idx = self.currentIndex()
        if idx < 0 or self.itemText(idx).strip().lower() != text.lower():
            idx = self.findText(text, Qt.MatchFlag.MatchFixedString)
        if idx < 0:
            raise ValueError(text)
        return self.itemData(idx)


def unit_choices(db: Database):
    return [(u["id"], u["name"]) for u in db.units()]


class PersonDialog(QDialog):
    """Картка військовослужбовця: дані + проходження служби."""

    def __init__(self, parent, db: Database, person_id=None, on_change=None,
                 default_unit_id=None):
        super().__init__(parent)
        self.db, self.person_id, self.on_change = db, person_id, on_change
        self.setWindowTitle("Нова особова справа" if person_id is None else "Особова справа")
        self.resize(720, 780)
        self._photo = None            # байти JPEG поточного фото
        self._photo_changed = False   # чи треба записати фото в базу при збереженні

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_card(), "Картка")
        self.tabs.addTab(self._build_events(), "Проходження служби")
        self.tabs.addTab(self._build_documents(), "Документи")

        save_btn = QPushButton("Зберегти")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.save)
        close_btn = QPushButton("Закрити")
        close_btn.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(save_btn)
        buttons.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.addWidget(self.tabs, 1)
        root.addLayout(buttons)

        self.widgets["unit_id"].set_choices(unit_choices(db))
        self.widgets["commander_id"].set_choices(db.people_options(exclude_id=person_id))
        if person_id is not None:
            self._load()
        elif default_unit_id:
            self.widgets["unit_id"].set_value(default_unit_id)
        self._show_id()
        self._update_events_state()

    # ---------- картка ----------
    def _build_card(self):
        self.widgets = {}
        form_host = QWidget()
        outer = QVBoxLayout(form_host)

        top = QHBoxLayout()
        self.photo_label = QLabel()
        self.photo_label.setFixedSize(PHOTO_W, PHOTO_H)
        self.photo_label.setFrameShape(QFrame.Shape.Box)
        self.photo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.photo_label)
        side = QVBoxLayout()
        side.addWidget(QLabel("ID (UUID)"))
        self.id_edit = QLineEdit()
        self.id_edit.setReadOnly(True)
        side.addWidget(self.id_edit)
        side.addSpacing(8)
        pick = QPushButton("Обрати фото…")
        pick.clicked.connect(self._choose_photo)
        drop = QPushButton("Видалити фото")
        drop.clicked.connect(self._remove_photo)
        side.addWidget(pick)
        side.addWidget(drop)
        side.addStretch(1)
        top.addLayout(side, 1)
        outer.addLayout(top)
        self._show_photo()

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        outer.addLayout(form)

        for key, label, kind, values in FORM_FIELDS:
            if kind == "line":
                w = QLineEdit()
            elif kind == "combo":
                w = SafeComboBox()
                w.setEditable(True)
                w.addItems(values)
            elif kind == "date":
                w = DateField()
            elif kind in ("unit", "person"):
                w = ChoiceBox()
            else:
                w = QPlainTextEdit()
                w.setFixedHeight(64)
                w.setTabChangesFocus(True)
            form.addRow(label, w)
            self.widgets[key] = w
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_host)
        return scroll

    def _show_id(self):
        self.id_edit.setText(self.person_id or "буде створено після збереження")

    def _get(self, key):
        w = self.widgets[key]
        if isinstance(w, ChoiceBox):      # перед QComboBox: це його підклас
            return w.value()
        if isinstance(w, QLineEdit):
            return w.text().strip()
        if isinstance(w, QComboBox):
            return w.currentText().strip()
        if isinstance(w, DateField):
            return w.iso()
        return w.toPlainText().strip()

    def _set(self, key, value):
        w = self.widgets[key]
        if isinstance(w, ChoiceBox):
            w.set_value(value)
        elif isinstance(w, QLineEdit):
            w.setText(value or "")
        elif isinstance(w, QComboBox):
            w.setCurrentText(value or "")
        elif isinstance(w, DateField):
            w.set_iso(value)
        else:
            w.setPlainText(value or "")

    def _load(self):
        row = self.db.get(self.person_id)
        for key in PERSON_FIELDS:
            self._set(key, row[key])
        self._photo = self.db.get_photo(self.person_id)
        self._photo_changed = False
        self._show_photo()
        self._refresh_events()

    def save(self):
        try:
            data = {k: self._get(k) for k in PERSON_FIELDS}
        except ValueError as e:
            QMessageBox.warning(
                self, "Увага", f"«{e}» немає у списку. Оберіть варіант зі списку "
                               "або залиште поле порожнім.")
            self.tabs.setCurrentIndex(0)
            return
        if not data["last_name"] or not data["first_name"]:
            QMessageBox.warning(self, "Увага", "Прізвище та ім'я обов'язкові.")
            self.tabs.setCurrentIndex(0)
            return
        try:
            self.person_id = self.db.save(data, self.person_id)
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Дублікат", "Особа з таким особовим номером уже існує.")
            return
        except ValueError as e:   # цикл у ланцюгу командирів
            QMessageBox.warning(self, "Командир", str(e))
            return
        if self._photo_changed:
            self.db.set_photo(self.person_id, self._photo)
            self._photo_changed = False
        self.setWindowTitle("Особова справа")
        self._show_id()
        self._update_events_state()
        if self.on_change:
            self.on_change()

    # ---------- проходження служби ----------
    def _build_events(self):
        page = QWidget()
        lay = QVBoxLayout(page)

        self.ev_table = QTableWidget(0, 3)
        self.ev_table.setHorizontalHeaderLabels(["Дата", "Тип", "Опис"])
        self.ev_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.ev_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.ev_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.ev_table.verticalHeader().setVisible(False)
        self.ev_table.setAlternatingRowColors(True)
        hdr = self.ev_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.ev_table, 1)

        self.ev_hint = QLabel("Спочатку збережіть картку, щоб додавати записи.")
        self.ev_hint.setEnabled(False)
        lay.addWidget(self.ev_hint)

        self.ev_panel = QWidget()
        panel = QHBoxLayout(self.ev_panel)
        panel.setContentsMargins(0, 0, 0, 0)
        self.ev_date = DateField(today=True)
        self.ev_type = SafeComboBox()
        self.ev_type.setEditable(True)
        self.ev_type.addItems(EVENT_TYPES)
        self.ev_desc = QLineEdit()
        self.ev_desc.setPlaceholderText("Опис")
        self.ev_desc.returnPressed.connect(self._add_event)
        add = QPushButton("Додати")
        add.clicked.connect(self._add_event)
        delete = QPushButton("Видалити вибраний")
        delete.clicked.connect(self._del_event)
        panel.addWidget(self.ev_date)
        panel.addWidget(self.ev_type)
        panel.addWidget(self.ev_desc, 1)
        panel.addWidget(add)
        panel.addWidget(delete)
        lay.addWidget(self.ev_panel)
        return page

    def _update_events_state(self):
        saved = self.person_id is not None
        self.ev_panel.setEnabled(saved)
        self.ev_hint.setVisible(not saved)
        self.doc_panel.setEnabled(saved)
        self.doc_hint.setVisible(not saved)
        if saved:
            self._refresh_events()
            self._refresh_docs()

    def _refresh_events(self):
        events = self.db.events(self.person_id)
        self.ev_table.setRowCount(len(events))
        for r, ev in enumerate(events):
            first = QTableWidgetItem(fmt_date(ev["date"]))
            first.setData(Qt.ItemDataRole.UserRole, ev["id"])
            self.ev_table.setItem(r, 0, first)
            self.ev_table.setItem(r, 1, QTableWidgetItem(ev["type"]))
            self.ev_table.setItem(r, 2, QTableWidgetItem(ev["description"]))

    def _add_event(self):
        iso = self.ev_date.iso() or datetime.now().strftime("%Y-%m-%d")
        etype = self.ev_type.currentText().strip()
        desc = self.ev_desc.text().strip()
        if not desc and not etype:
            return
        self.db.add_event(self.person_id, iso, etype, desc)
        self.ev_desc.clear()
        self._refresh_events()

    def _del_event(self):
        row = self.ev_table.currentRow()
        if row < 0:
            return
        if QMessageBox.question(self, "Видалення", "Видалити вибраний запис?") \
                == QMessageBox.StandardButton.Yes:
            event_id = self.ev_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            self.db.delete_event(event_id)
            self._refresh_events()

    # ---------- фото ----------
    def _show_photo(self):
        if self._photo:
            pix = QPixmap()
            if pix.loadFromData(self._photo):
                self.photo_label.setPixmap(pix.scaled(
                    PHOTO_W, PHOTO_H, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
                return
        self.photo_label.clear()
        self.photo_label.setText("Немає фото")

    def _choose_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Обрати фото", "",
            "Зображення (*.jpg *.jpeg *.png *.bmp *.webp);;Усі файли (*)")
        if not path:
            return
        reader = QImageReader(path)
        reader.setAutoTransform(True)       # враховує поворот із EXIF (фото з телефона)
        img = reader.read()
        if img.isNull():
            QMessageBox.warning(self, "Фото", "Не вдалося прочитати зображення.")
            return
        if img.width() > PHOTO_MAX_W or img.height() > PHOTO_MAX_H:
            img = img.scaled(PHOTO_MAX_W, PHOTO_MAX_H, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        ok = img.save(buf, "JPEG", 88)
        buf.close()
        if not ok:
            QMessageBox.warning(self, "Фото", "Не вдалося обробити зображення.")
            return
        self._photo = bytes(data)
        self._photo_changed = True
        self._show_photo()

    def _remove_photo(self):
        if self._photo:
            self._photo = None
            self._photo_changed = True
            self._show_photo()

    # ---------- документи (скани) ----------
    def _build_documents(self):
        page = QWidget()
        lay = QVBoxLayout(page)

        self.doc_table = QTableWidget(0, 5)
        self.doc_table.setHorizontalHeaderLabels(["Назва", "Тип", "Файл", "Розмір", "Додано"])
        self.doc_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.doc_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.doc_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.doc_table.verticalHeader().setVisible(False)
        self.doc_table.setAlternatingRowColors(True)
        hdr = self.doc_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 4):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.doc_table.doubleClicked.connect(lambda _: self._open_doc())
        lay.addWidget(self.doc_table, 1)

        self.doc_hint = QLabel("Спочатку збережіть картку, щоб додавати документи.")
        self.doc_hint.setEnabled(False)
        lay.addWidget(self.doc_hint)

        self.doc_panel = QWidget()
        panel = QVBoxLayout(self.doc_panel)
        panel.setContentsMargins(0, 0, 0, 0)

        actions = QHBoxLayout()
        for text, slot in (("Відкрити", self._open_doc), ("Зберегти як…", self._save_doc_as),
                           ("Перейменувати", self._rename_doc), ("Видалити", self._del_doc)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            actions.addWidget(b)
        actions.addStretch(1)
        panel.addLayout(actions)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Тип нових документів:"))
        self.doc_type = SafeComboBox()
        self.doc_type.setEditable(True)
        self.doc_type.addItems(DOC_TYPES)
        self.doc_type.setCurrentText("Інше")
        add_row.addWidget(self.doc_type, 1)
        add = QPushButton("Додати файли…")
        add.clicked.connect(self._add_docs)
        add_row.addWidget(add)
        panel.addLayout(add_row)
        lay.addWidget(self.doc_panel)
        return page

    def _refresh_docs(self):
        docs = self.db.documents(self.person_id)
        self.doc_table.setRowCount(len(docs))
        for r, d in enumerate(docs):
            first = QTableWidgetItem(d["title"])
            first.setData(Qt.ItemDataRole.UserRole, d["id"])
            self.doc_table.setItem(r, 0, first)
            self.doc_table.setItem(r, 1, QTableWidgetItem(d["doc_type"]))
            self.doc_table.setItem(r, 2, QTableWidgetItem(d["filename"]))
            self.doc_table.setItem(r, 3, QTableWidgetItem(fmt_size(d["size"])))
            self.doc_table.setItem(r, 4, QTableWidgetItem(fmt_datetime(d["added_at"])))
        self.tabs.setTabText(2, f"Документи ({len(docs)})" if docs else "Документи")

    def _selected_doc_id(self):
        row = self.doc_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Увага", "Оберіть документ у списку.")
            return None
        return self.doc_table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def _add_docs(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Додати документи", "",
            "Документи і скани (*.pdf *.jpg *.jpeg *.png *.tif *.tiff *.bmp *.doc *.docx);;"
            "Усі файли (*)")
        for p in paths:
            path = Path(p)
            try:
                if path.stat().st_size > MAX_DOC_BYTES:
                    QMessageBox.warning(
                        self, "Файл завеликий",
                        f"«{path.name}» більший за {MAX_DOC_BYTES // 1024 // 1024} МБ і не доданий.")
                    continue
                data = path.read_bytes()
            except OSError as e:
                QMessageBox.warning(self, "Помилка читання", f"«{path.name}»: {e}")
                continue
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.db.add_document(self.person_id, path.stem, self.doc_type.currentText(),
                                 path.name, data, mime)
        if paths:
            self._refresh_docs()

    def _open_doc(self):
        doc_id = self._selected_doc_id()
        if doc_id is None:
            return
        row = self.db.get_document(doc_id)
        try:
            open_blob(self, row["filename"], bytes(row["data"]))
        except OSError as e:
            QMessageBox.warning(self, "Відкриття файлу", str(e))

    def _save_doc_as(self):
        doc_id = self._selected_doc_id()
        if doc_id is None:
            return
        row = self.db.get_document(doc_id)
        path, _ = QFileDialog.getSaveFileName(self, "Зберегти файл", row["filename"])
        if not path:
            return
        try:
            Path(path).write_bytes(bytes(row["data"]))
        except OSError as e:
            QMessageBox.warning(self, "Помилка запису", str(e))
            return
        QMessageBox.information(self, "Готово", f"Файл збережено:\n{path}")

    def _rename_doc(self):
        doc_id = self._selected_doc_id()
        if doc_id is None:
            return
        row = self.db.get_document(doc_id)
        title, ok = QInputDialog.getText(
            self, "Перейменувати", "Назва документа:", QLineEdit.EchoMode.Normal, row["title"])
        if ok and title.strip():
            self.db.rename_document(doc_id, title)
            self._refresh_docs()

    def _del_doc(self):
        doc_id = self._selected_doc_id()
        if doc_id is None:
            return
        if QMessageBox.question(self, "Видалення", "Видалити вибраний документ?") \
                == QMessageBox.StandardButton.Yes:
            self.db.delete_document(doc_id)
            self._refresh_docs()


class UnitEditDialog(QDialog):
    """Створення / редагування підрозділу."""

    def __init__(self, parent, db: Database, unit_id=None):
        super().__init__(parent)
        self.db, self.unit_id = db, unit_id
        self.setWindowTitle("Новий підрозділ" if unit_id is None else "Підрозділ")
        self.resize(480, 160)

        self.name = QLineEdit()
        self.name.setPlaceholderText("Наприклад: Взвод зв'язку")
        self.commander = ChoiceBox()
        self.commander.set_choices(db.people_options())

        form = QFormLayout()
        form.addRow("Назва *", self.name)
        form.addRow("Командир підрозділу", self.commander)

        save = QPushButton("Зберегти")
        save.setDefault(True)
        save.clicked.connect(self._save)
        cancel = QPushButton("Скасувати")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(save)
        buttons.addWidget(cancel)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addStretch(1)
        root.addLayout(buttons)

        if unit_id is not None:
            row = db.get_unit(unit_id)
            self.name.setText(row["name"])
            self.commander.set_value(row["commander_id"])

    def _save(self):
        name = self.name.text().strip()
        if not name:
            QMessageBox.warning(self, "Увага", "Вкажіть назву підрозділу.")
            return
        try:
            commander = self.commander.value()
        except ValueError as e:
            QMessageBox.warning(
                self, "Увага", f"«{e}» немає у списку. Оберіть командира зі списку "
                               "або залиште поле порожнім.")
            return
        try:
            self.db.save_unit(name, commander, self.unit_id)
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Дублікат", "Підрозділ з такою назвою вже існує.")
            return
        self.accept()


class UnitsDialog(QDialog):
    """Список підрозділів: додати, змінити, видалити."""

    def __init__(self, parent, db: Database, on_change=None):
        super().__init__(parent)
        self.db, self.on_change = db, on_change
        self.setWindowTitle("Підрозділи")
        self.resize(680, 440)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Підрозділ", "Командир підрозділу", "Особового складу"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(lambda _: self.edit())

        buttons = QHBoxLayout()
        for text, slot in (("Додати", self.add), ("Змінити", self.edit),
                           ("Видалити", self.delete)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch(1)
        close = QPushButton("Закрити")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)

        root = QVBoxLayout(self)
        root.addWidget(self.table, 1)
        root.addLayout(buttons)
        self.refresh()

    def refresh(self):
        units = self.db.units()
        self.table.setRowCount(len(units))
        for r, u in enumerate(units):
            first = QTableWidgetItem(u["name"])
            first.setData(Qt.ItemDataRole.UserRole, u["id"])
            self.table.setItem(r, 0, first)
            self.table.setItem(r, 1, QTableWidgetItem(u["commander_name"]))
            self.table.setItem(r, 2, QTableWidgetItem(str(u["member_count"])))

    def _selected(self):
        row = self.table.currentRow()
        return None if row < 0 else self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def _changed(self):
        self.refresh()
        if self.on_change:
            self.on_change()

    def add(self):
        if UnitEditDialog(self, self.db).exec():
            self._changed()

    def edit(self):
        uid = self._selected()
        if uid is None:
            QMessageBox.information(self, "Увага", "Оберіть підрозділ у списку.")
            return
        if UnitEditDialog(self, self.db, uid).exec():
            self._changed()

    def delete(self):
        uid = self._selected()
        if uid is None:
            return
        answer = QMessageBox.question(
            self, "Видалення",
            "Видалити підрозділ? Особи з нього залишаться без підрозділу.")
        if answer == QMessageBox.StandardButton.Yes:
            self.db.delete_unit(uid)
            self._changed()


def apply_theme(app: QApplication, dark: bool):
    app.setStyle("Fusion")
    if not dark:
        app.setPalette(app.style().standardPalette())
        return
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: QColor(37, 37, 38),
        QPalette.ColorRole.WindowText: QColor(230, 230, 230),
        QPalette.ColorRole.Base: QColor(30, 30, 30),
        QPalette.ColorRole.AlternateBase: QColor(43, 43, 46),
        QPalette.ColorRole.ToolTipBase: QColor(60, 60, 62),
        QPalette.ColorRole.ToolTipText: QColor(230, 230, 230),
        QPalette.ColorRole.Text: QColor(230, 230, 230),
        QPalette.ColorRole.PlaceholderText: QColor(130, 130, 130),
        QPalette.ColorRole.Button: QColor(53, 53, 55),
        QPalette.ColorRole.ButtonText: QColor(230, 230, 230),
        QPalette.ColorRole.BrightText: QColor(255, 80, 80),
        QPalette.ColorRole.Link: QColor(80, 160, 255),
        QPalette.ColorRole.Highlight: QColor(42, 130, 218),
        QPalette.ColorRole.HighlightedText: QColor(255, 255, 255),
    }
    for role, color in roles.items():
        p.setColor(role, color)
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(120, 120, 120))
    app.setPalette(p)


class MainWindow(QMainWindow):
    COLUMNS = ("ПІБ", "Звання", "Посада", "Підрозділ", "Статус", "Місце перебування",
               "Особовий №", "Безпосередній командир")
    WIDTHS = (250, 140, 170, 150, 110, 170, 100, 230)
    TREE_COLUMNS = ("Підрозділ / ПІБ", "Звання", "Посада", "Статус", "Місце перебування",
                    "Особовий №", "Командир")
    TREE_WIDTHS = (330, 150, 180, 120, 170, 110, 260)

    def __init__(self, db_path=None):
        super().__init__()
        db_path = db_path or paths.DB_PATH
        self.setWindowTitle("Облік особових справ")
        self.resize(1150, 640)
        self.db = Database(db_path)
        self.settings = QSettings("PersonnelApp", "Personnel")
        self.mode = self.settings.value("mode", "list")
        if self.mode not in ("list", "tree"):
            self.mode = "list"

        self._build_toolbar()

        # --- режим «Список» ---
        self.model = QStandardItemModel(0, len(self.COLUMNS))
        self.model.setHorizontalHeaderLabels(self.COLUMNS)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setAlternatingRowColors(True)
        self.view.setSortingEnabled(True)
        self.view.verticalHeader().setVisible(False)
        self.view.horizontalHeader().setStretchLastSection(True)
        for i, w in enumerate(self.WIDTHS):
            self.view.setColumnWidth(i, w)
        self.view.doubleClicked.connect(lambda _: self.edit())

        # --- режим «За підрозділами» ---
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(self.TREE_COLUMNS))
        self.tree.setHeaderLabels(self.TREE_COLUMNS)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for i, w in enumerate(self.TREE_WIDTHS):
            self.tree.setColumnWidth(i, w)
        self.tree.header().setStretchLastSection(True)
        self.tree.itemDoubleClicked.connect(self._tree_double_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.tree)
        self.stack.setCurrentIndex(1 if self.mode == "tree" else 0)
        self.setCentralWidget(self.stack)

        self.count_label = QLabel()
        self.statusBar().addPermanentWidget(self.count_label)

        self.refresh()
        if self.db.migration_backup:
            QTimer.singleShot(300, self._notify_migration)

    def _notify_migration(self):
        QMessageBox.information(
            self, "База оновлена",
            "Базу перенесено в нову схему: особам присвоєно UUID, підрозділи "
            "винесено в окремий список.\n\nРезервна копія старої бази:\n"
            f"{self.db.migration_backup}")

    # ---------- інтерфейс ----------
    def _build_toolbar(self):
        bar = QToolBar("Головна")
        bar.setMovable(False)
        self.addToolBar(bar)

        def action(text, slot, shortcut=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            bar.addAction(a)
            return a

        action("Додати", self.add, "Ctrl+N")
        action("Відкрити", self.edit)
        action("Видалити", self.delete)
        bar.addSeparator()
        action("Підрозділи", self.manage_units)
        bar.addSeparator()

        group = QActionGroup(self)
        group.setExclusive(True)
        for mode, text in (("list", "Список"), ("tree", "За підрозділами")):
            a = QAction(text, self)
            a.setCheckable(True)
            a.setChecked(self.mode == mode)
            a.triggered.connect(lambda _checked, m=mode: self.set_mode(m))
            group.addAction(a)
            bar.addAction(a)
        bar.addSeparator()

        action("Експорт CSV", self.export_csv)
        action("Резервна копія", self.backup)
        bar.addSeparator()
        dark = QAction("Темна тема", self)
        dark.setCheckable(True)
        dark.setChecked(self.settings.value("dark", False, type=bool))
        dark.toggled.connect(self._toggle_theme)
        bar.addAction(dark)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Пошук (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(self.search)
        focus = QAction(self)
        focus.setShortcut(QKeySequence("Ctrl+F"))
        focus.triggered.connect(lambda: (self.search.setFocus(), self.search.selectAll()))
        self.addAction(focus)

    def _toggle_theme(self, dark: bool):
        self.settings.setValue("dark", dark)
        apply_theme(QApplication.instance(), dark)

    def set_mode(self, mode: str):
        self.mode = mode
        self.settings.setValue("mode", mode)
        self.stack.setCurrentIndex(1 if mode == "tree" else 0)
        self.refresh()

    # ---------- дані ----------
    def refresh(self, *_):
        rows = self.db.search(self.search.text())
        if self.mode == "tree":
            self._fill_tree(rows)
        else:
            self._fill_table(rows)
        self.count_label.setText(f"Записів: {len(rows)}")

    @staticmethod
    def _full_name(r):
        return f"{r['last_name']} {r['first_name']} {r['middle_name']}".strip()

    def _fill_table(self, rows):
        self.model.removeRows(0, self.model.rowCount())
        for r in rows:
            items = [QStandardItem(str(v)) for v in (
                self._full_name(r), r["rank"], r["position"], r["unit_name"],
                r["status"], r["location"], r["personal_number"], r["commander_name"])]
            items[0].setData(r["id"], Qt.ItemDataRole.UserRole)
            self.model.appendRow(items)

    def _fill_tree(self, rows):
        query = self.search.text().strip()
        expanded = set()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.isExpanded():
                expanded.add(top.data(0, Qt.ItemDataRole.UserRole)[1])
        self.tree.clear()

        by_unit = {}
        for r in rows:
            by_unit.setdefault(r["unit_id"], []).append(r)

        def bold(item):
            f = item.font(0)
            f.setBold(True)
            item.setFont(0, f)

        def add_person(parent, r, is_commander=False):
            child = QTreeWidgetItem([
                self._full_name(r), r["rank"], r["position"], r["status"],
                r["location"], r["personal_number"], r["commander_name"]])
            child.setData(0, Qt.ItemDataRole.UserRole, ["person", r["id"]])
            if is_commander:
                bold(child)
            parent.addChild(child)

        for u in self.db.units():
            members = by_unit.get(u["id"], [])
            if query and not members:
                continue
            count = len(members) if query else u["member_count"]
            cmd = f"Командир: {u['commander_name']}" if u["commander_name"] else ""
            top = QTreeWidgetItem([f"{u['name']} ({count})", "", "", "", "", "", cmd])
            top.setData(0, Qt.ItemDataRole.UserRole, ["unit", u["id"]])
            bold(top)
            self.tree.addTopLevelItem(top)
            for r in members:
                add_person(top, r, is_commander=(r["id"] == u["commander_id"]))
            top.setExpanded(bool(query) or u["id"] in expanded)

        orphans = by_unit.get(None, [])
        if orphans:
            top = QTreeWidgetItem([f"Без підрозділу ({len(orphans)})", "", "", "", "", "", ""])
            top.setData(0, Qt.ItemDataRole.UserRole, ["none", None])
            bold(top)
            self.tree.addTopLevelItem(top)
            for r in orphans:
                add_person(top, r)
            top.setExpanded(bool(query) or None in expanded)

    def _current(self):
        """(вид, id) вибраного рядка: ('person'|'unit'|'none'|None, id|None)."""
        if self.mode == "tree":
            item = self.tree.currentItem()
            if item is None:
                return None, None
            kind, ident = item.data(0, Qt.ItemDataRole.UserRole)
            return kind, ident
        idx = self.view.currentIndex()
        if not idx.isValid():
            return None, None
        src = self.proxy.mapToSource(idx)
        return "person", self.model.item(src.row(), 0).data(Qt.ItemDataRole.UserRole)

    # ---------- дії ----------
    def add(self, unit_id=None):
        if not isinstance(unit_id, str):   # сигнал triggered передає bool
            unit_id = None
            kind, ident = self._current()
            if self.mode == "tree" and kind == "unit":
                unit_id = ident
            elif self.mode == "tree" and kind == "person":
                unit_id = self.db.get(ident)["unit_id"]
        PersonDialog(self, self.db, None, on_change=self.refresh,
                     default_unit_id=unit_id).exec()

    def edit(self):
        kind, ident = self._current()
        if kind == "person":
            self.open_person(ident)
        elif kind == "unit":
            self.edit_unit(ident)
        else:
            QMessageBox.information(self, "Увага", "Оберіть запис у списку.")

    def open_person(self, person_id):
        PersonDialog(self, self.db, person_id, on_change=self.refresh).exec()

    def edit_unit(self, unit_id):
        if UnitEditDialog(self, self.db, unit_id).exec():
            self.refresh()

    def manage_units(self):
        UnitsDialog(self, self.db, on_change=self.refresh).exec()
        self.refresh()

    def delete(self):
        kind, ident = self._current()
        if kind == "unit":
            QMessageBox.information(
                self, "Підрозділ",
                "Підрозділи видаляються у вікні «Підрозділи» на панелі інструментів.")
            return
        if kind != "person":
            return
        text = ("Видалити особову справу разом з історією служби, фото та документами?\n"
                "Дію не можна скасувати.")
        subs, units = self.db.commander_links(ident)
        if subs or units:
            text += (f"\n\nЦя особа є командиром: осіб — {subs}, підрозділів — {units}. "
                     "У них поле командира буде очищено.")
        if QMessageBox.question(self, "Видалення", text) == QMessageBox.StandardButton.Yes:
            self.db.delete(ident)
            self.refresh()

    def _tree_double_clicked(self, item, _column):
        kind, ident = item.data(0, Qt.ItemDataRole.UserRole)
        if kind == "person":
            self.open_person(ident)

    def _tree_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        kind, ident = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        if kind == "person":
            menu.addAction("Відкрити справу", lambda: self.open_person(ident))
        elif kind == "unit":
            menu.addAction("Редагувати підрозділ", lambda: self.edit_unit(ident))
            menu.addAction("Додати особу в підрозділ", lambda: self.add(ident))
        else:
            return
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def export_csv(self):
        paths.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        default = f"personnel_{datetime.now():%Y%m%d_%H%M}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Експорт у CSV", str(paths.EXPORT_DIR / default), "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(EXPORT_KEYS)
            for r in self.db.search(self.search.text()):
                writer.writerow([fmt_date(r[k]) if k in DATE_FIELDS else (r[k] or "")
                                 for k in EXPORT_KEYS])
        QMessageBox.information(self, "Готово", f"Експортовано до:\n{path}")

    def backup(self):
        paths.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        default = f"personnel_{datetime.now():%Y%m%d_%H%M}.db"
        path, _ = QFileDialog.getSaveFileName(
            self, "Резервна копія", str(paths.BACKUP_DIR / default), "SQLite (*.db)")
        if not path:
            return
        dest = sqlite3.connect(path)
        with dest:
            self.db.conn.backup(dest)
        dest.close()
        QMessageBox.information(self, "Готово", f"Резервну копію збережено:\n{path}")

    def closeEvent(self, event):
        self.db.close()
        cleanup_temp()   # прибрати тимчасові копії відкритих документів
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    settings = QSettings("PersonnelApp", "Personnel")
    apply_theme(app, settings.value("dark", False, type=bool))
    paths.ensure_dirs()
    moved = paths.migrate_legacy_files()   # стара база поруч із програмою -> app_data
    paths.clean_temp()
    window = MainWindow()
    window.show()
    if moved:
        QTimer.singleShot(400, lambda: QMessageBox.information(
            window, "Файли перенесено",
            f"Дані програми тепер зберігаються в папці:\n{paths.DATA_DIR}\n\n"
            "Перенесено: " + ", ".join(moved)))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

"""Шар роботи з базою даних (SQLite) для обліку особових справ.

Схема (версія з UUID):
  unit   — підрозділи (id UUID, назва, командир підрозділу -> person)
  person — особові справи (id UUID, підрозділ -> unit, безпосередній командир -> person)
  event  — проходження служби (запис належить особі)

Стара база (з числовими id та текстовим полем «підрозділ») автоматично
переноситься в нову схему при першому відкритті, а перед цим створюється
резервна копія поруч із файлом бази.
"""
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

PERSON_FIELDS = [
    "last_name", "first_name", "middle_name", "birth_date", "personal_number",
    "rank", "position", "unit_id", "status", "location", "enlist_date",
    "phone", "address", "education", "family", "commander_id", "notes",
]
REF_FIELDS = ("unit_id", "commander_id")  # необов'язкові посилання (NULL, якщо не задано)

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS unit (
        id           TEXT PRIMARY KEY NOT NULL,
        name         TEXT NOT NULL UNIQUE,
        commander_id TEXT REFERENCES person(id) ON DELETE SET NULL
    )""",
    """CREATE TABLE IF NOT EXISTS person (
        id              TEXT PRIMARY KEY NOT NULL,
        last_name       TEXT NOT NULL,
        first_name      TEXT NOT NULL,
        middle_name     TEXT NOT NULL DEFAULT '',
        birth_date      TEXT NOT NULL DEFAULT '',
        personal_number TEXT NOT NULL DEFAULT '',
        rank            TEXT NOT NULL DEFAULT '',
        position        TEXT NOT NULL DEFAULT '',
        unit_id         TEXT REFERENCES unit(id) ON DELETE SET NULL,
        status          TEXT NOT NULL DEFAULT '',
        location        TEXT NOT NULL DEFAULT '',
        enlist_date     TEXT NOT NULL DEFAULT '',
        phone           TEXT NOT NULL DEFAULT '',
        address         TEXT NOT NULL DEFAULT '',
        education       TEXT NOT NULL DEFAULT '',
        family          TEXT NOT NULL DEFAULT '',
        commander_id    TEXT REFERENCES person(id) ON DELETE SET NULL,
        notes           TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_person_number "
    "ON person(personal_number) WHERE personal_number <> ''",
    "CREATE INDEX IF NOT EXISTS idx_person_unit ON person(unit_id)",
    "CREATE INDEX IF NOT EXISTS idx_person_commander ON person(commander_id)",
    """CREATE TABLE IF NOT EXISTS event (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id   TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
        date        TEXT NOT NULL,
        type        TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS idx_event_person ON event(person_id, date)",
    # Фото і скани зберігаються в самій базі (BLOB): один файл — одна резервна копія.
    # Вони винесені в окремі таблиці, щоб списки осіб не тягнули важкі дані.
    """CREATE TABLE IF NOT EXISTS photo (
        person_id TEXT PRIMARY KEY NOT NULL REFERENCES person(id) ON DELETE CASCADE,
        mime      TEXT NOT NULL DEFAULT 'image/jpeg',
        data      BLOB NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS document (
        id        TEXT PRIMARY KEY NOT NULL,
        person_id TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
        title     TEXT NOT NULL,
        doc_type  TEXT NOT NULL DEFAULT '',
        filename  TEXT NOT NULL DEFAULT '',
        mime      TEXT NOT NULL DEFAULT '',
        size      INTEGER NOT NULL DEFAULT 0,
        added_at  TEXT NOT NULL,
        data      BLOB NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_document_person ON document(person_id)",
)

# Вираз «Звання Прізвище Ім'я» для командира (c — таблиця person)
_CMD_NAME = ("TRIM(COALESCE(c.rank, '') || ' ' || COALESCE(c.last_name, '') || ' ' "
             "|| COALESCE(c.first_name, ''))")

PERSON_SELECT = f"""
SELECT p.*,
       COALESCE(u.name, '') AS unit_name,
       {_CMD_NAME} AS commander_name
FROM person p
LEFT JOIN unit u ON u.id = p.unit_id
LEFT JOIN person c ON c.id = p.commander_id
"""


def new_id() -> str:
    return str(uuid.uuid4())


def parse_date(text: str) -> str:
    """'ДД.ММ.РРРР' -> 'РРРР-ММ-ДД'. Порожній рядок лишається порожнім."""
    text = (text or "").strip()
    if not text:
        return ""
    return datetime.strptime(text, "%d.%m.%Y").strftime("%Y-%m-%d")


def fmt_date(iso: str) -> str:
    """'РРРР-ММ-ДД' -> 'ДД.ММ.РРРР'."""
    if not iso:
        return ""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return iso


class Database:
    def __init__(self, path):
        self.migration_backup = None  # шлях до копії, якщо була міграція
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        # SQLite LIKE не враховує регістр для кирилиці, тому власна функція
        self.conn.create_function("lower_u", 1, lambda s: (s or "").lower())
        for stmt in SCHEMA:
            self.conn.execute(stmt)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ---------- особовий склад ----------
    def search(self, query: str = ""):
        query = (query or "").strip().lower()
        sql = PERSON_SELECT
        params = []
        if query:
            cols = ["p.last_name", "p.first_name", "p.middle_name", "p.personal_number",
                    "p.rank", "p.position", "p.status", "u.name"]
            sql += " WHERE " + " OR ".join(f"lower_u({c}) LIKE ?" for c in cols)
            params = [f"%{query}%"] * len(cols)
        sql += " ORDER BY lower_u(p.last_name), lower_u(p.first_name)"
        return self.conn.execute(sql, params).fetchall()

    def get(self, person_id: str):
        return self.conn.execute(
            PERSON_SELECT + " WHERE p.id = ?", (person_id,)).fetchone()

    def people_options(self, exclude_id=None):
        """Список [(id, підпис)] для вибору командира."""
        rows = self.conn.execute(
            "SELECT id, last_name, first_name, middle_name, rank "
            "FROM person ORDER BY lower_u(last_name), lower_u(first_name)").fetchall()
        out = []
        for r in rows:
            if exclude_id and r["id"] == exclude_id:
                continue
            label = " ".join(x for x in (r["rank"], r["last_name"],
                                         r["first_name"], r["middle_name"]) if x)
            out.append((r["id"], label))
        return out

    def _check_commander(self, person_id, commander_id):
        """Забороняє циклічне підпорядкування (A -> B -> A, A -> A)."""
        if not commander_id or person_id is None:
            return
        seen, cur = set(), commander_id
        while cur and cur not in seen:
            if cur == person_id:
                raise ValueError(
                    "Командир не може (прямо чи через ланцюг підпорядкування) "
                    "підпорядковуватися цій самій особі.")
            seen.add(cur)
            row = self.conn.execute(
                "SELECT commander_id FROM person WHERE id = ?", (cur,)).fetchone()
            cur = row[0] if row else None

    def save(self, data: dict, person_id: str | None = None) -> str:
        """Створює або оновлює запис і повертає UUID особи.
        sqlite3.IntegrityError — якщо особовий номер уже існує;
        ValueError — якщо командир створює цикл підпорядкування."""
        data = dict(data)
        for k in REF_FIELDS:
            data[k] = data.get(k) or None
        self._check_commander(person_id, data["commander_id"])
        values = [data.get(f) if f in REF_FIELDS else data.get(f, "")
                  for f in PERSON_FIELDS]
        with self.conn:
            if person_id is None:
                person_id = new_id()
                self.conn.execute(
                    f"INSERT INTO person (id, {', '.join(PERSON_FIELDS)}) "
                    f"VALUES (?, {', '.join('?' * len(PERSON_FIELDS))})",
                    [person_id] + values)
            else:
                sets = ", ".join(f"{f} = ?" for f in PERSON_FIELDS)
                self.conn.execute(
                    f"UPDATE person SET {sets} WHERE id = ?", values + [person_id])
        return person_id

    def commander_links(self, person_id: str):
        """Скільки осіб і підрозділів мають цю особу командиром."""
        subs = self.conn.execute(
            "SELECT COUNT(*) FROM person WHERE commander_id = ?", (person_id,)).fetchone()[0]
        units = self.conn.execute(
            "SELECT COUNT(*) FROM unit WHERE commander_id = ?", (person_id,)).fetchone()[0]
        return subs, units

    def delete(self, person_id: str):
        with self.conn:
            self.conn.execute("DELETE FROM person WHERE id = ?", (person_id,))

    # ---------- підрозділи ----------
    def units(self):
        return self.conn.execute(
            f"""SELECT u.id, u.name, u.commander_id,
                       {_CMD_NAME} AS commander_name,
                       (SELECT COUNT(*) FROM person p WHERE p.unit_id = u.id) AS member_count
                FROM unit u
                LEFT JOIN person c ON c.id = u.commander_id
                ORDER BY lower_u(u.name)""").fetchall()

    def get_unit(self, unit_id: str):
        return self.conn.execute(
            "SELECT * FROM unit WHERE id = ?", (unit_id,)).fetchone()

    def save_unit(self, name: str, commander_id=None, unit_id: str | None = None) -> str:
        """sqlite3.IntegrityError — якщо підрозділ з такою назвою вже існує."""
        name = name.strip()
        commander_id = commander_id or None
        with self.conn:
            if unit_id is None:
                unit_id = new_id()
                self.conn.execute(
                    "INSERT INTO unit (id, name, commander_id) VALUES (?, ?, ?)",
                    (unit_id, name, commander_id))
            else:
                self.conn.execute(
                    "UPDATE unit SET name = ?, commander_id = ? WHERE id = ?",
                    (name, commander_id, unit_id))
        return unit_id

    def delete_unit(self, unit_id: str):
        """Особи з цього підрозділу лишаються без підрозділу."""
        with self.conn:
            self.conn.execute("DELETE FROM unit WHERE id = ?", (unit_id,))

    # ---------- проходження служби ----------
    def events(self, person_id: str):
        return self.conn.execute(
            "SELECT * FROM event WHERE person_id = ? ORDER BY date, id",
            (person_id,)).fetchall()

    def add_event(self, person_id: str, iso_date: str, etype: str, description: str):
        with self.conn:
            self.conn.execute(
                "INSERT INTO event (person_id, date, type, description) "
                "VALUES (?, ?, ?, ?)", (person_id, iso_date, etype, description))

    def delete_event(self, event_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM event WHERE id = ?", (event_id,))

    # ---------- фото ----------
    def get_photo(self, person_id: str) -> bytes | None:
        row = self.conn.execute(
            "SELECT data FROM photo WHERE person_id = ?", (person_id,)).fetchone()
        return bytes(row["data"]) if row else None

    def set_photo(self, person_id: str, data: bytes | None, mime: str = "image/jpeg"):
        """Зберігає (або замінює) фото; data=None — видаляє."""
        with self.conn:
            if not data:
                self.conn.execute("DELETE FROM photo WHERE person_id = ?", (person_id,))
                return
            self.conn.execute(
                "INSERT INTO photo (person_id, mime, data) VALUES (?, ?, ?) "
                "ON CONFLICT(person_id) DO UPDATE SET mime = excluded.mime, data = excluded.data",
                (person_id, mime, data))

    # ---------- документи (скани) ----------
    def documents(self, person_id: str):
        """Список документів особи БЕЗ вмісту файлів."""
        return self.conn.execute(
            "SELECT id, title, doc_type, filename, mime, size, added_at "
            "FROM document WHERE person_id = ? ORDER BY added_at, rowid",
            (person_id,)).fetchall()

    def add_document(self, person_id: str, title: str, doc_type: str,
                     filename: str, data: bytes, mime: str = "") -> str:
        doc_id = new_id()
        with self.conn:
            self.conn.execute(
                "INSERT INTO document (id, person_id, title, doc_type, filename, mime, "
                "size, added_at, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, person_id, title.strip() or filename, doc_type.strip(), filename,
                 mime, len(data), datetime.now().strftime("%Y-%m-%d %H:%M"), data))
        return doc_id

    def get_document(self, doc_id: str):
        """Запис разом із вмістом файлу (поле data)."""
        return self.conn.execute(
            "SELECT * FROM document WHERE id = ?", (doc_id,)).fetchone()

    def rename_document(self, doc_id: str, title: str):
        with self.conn:
            self.conn.execute(
                "UPDATE document SET title = ? WHERE id = ?", (title.strip(), doc_id))

    def delete_document(self, doc_id: str):
        with self.conn:
            self.conn.execute("DELETE FROM document WHERE id = ?", (doc_id,))

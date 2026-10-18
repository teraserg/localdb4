"""Розташування файлів програми.

Усе, що створює програма, лежить в одній папці app_data поруч із програмою
(або поруч із .exe, якщо програму зібрано через PyInstaller):

    app_data/
        personnel.db   — база даних (особи, підрозділи, фото, скани)
        backups/       — резервні копії та копії перед міграцією бази
        exports/       — експорт у CSV
        temp/          — тимчасові копії відкритих документів (очищується)

Іншу папку можна задати змінною середовища PERSONNEL_DATA_DIR.
"""
import os
import shutil
import sys
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):          # PyInstaller
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = _base_dir()
DATA_DIR = Path(os.environ.get("PERSONNEL_DATA_DIR") or (APP_DIR / "app_data")).resolve()
DB_PATH = DATA_DIR / "personnel.db"
BACKUP_DIR = DATA_DIR / "backups"
EXPORT_DIR = DATA_DIR / "exports"
TEMP_DIR = DATA_DIR / "temp"


def ensure_dirs():
    for d in (DATA_DIR, BACKUP_DIR, EXPORT_DIR, TEMP_DIR):
        d.mkdir(parents=True, exist_ok=True)


def migrate_legacy_files(old_dir: Path = None) -> list:
    """Переносить базу й копії, що лежали поруч із програмою (старе розташування),
    в app_data. Існуючі файли в app_data не перезаписуються.
    Повертає список перенесених файлів (імена)."""
    old = Path(old_dir) if old_dir else APP_DIR
    if old.resolve() == DATA_DIR:
        return []
    moved = []

    def move(src: Path, dst: Path):
        if src.exists() and not dst.exists():
            shutil.move(str(src), str(dst))
            moved.append(src.name)

    move(old / "personnel.db", DB_PATH)   # якщо в app_data вже є база — стару не чіпаємо
    for suffix in ("-journal", "-wal", "-shm"):   # хвости незакритої бази
        if (DB_PATH.parent / ("personnel.db" + suffix)).exists():
            continue
        move(old / ("personnel.db" + suffix), DB_PATH.parent / ("personnel.db" + suffix))
    for f in sorted(old.glob("personnel_before_uuid_*.db")):
        move(f, BACKUP_DIR / f.name)
    return moved


def clean_temp():
    """Видаляє залишки тимчасових копій (наприклад, після аварійного закриття)."""
    if not TEMP_DIR.exists():
        return
    for item in TEMP_DIR.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            try:
                item.unlink()
            except OSError:
                pass

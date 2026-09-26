"""Общее состояние нескольких воркеров uvicorn через файлы.

Каждый воркер — отдельный процесс со своей памятью. Чтобы добавленное
закрытие маршрута, принятый батч валидаций или перезагрузка прогноза были
видны сразу во всех процессах, изменяемое состояние живёт в файлах, а
процесс перечитывает файл, как только меняется его подпись.

Подпись файла — (mtime_ns, size, inode). Запись идёт через временный файл
и os.replace, поэтому каждая запись даёт новый inode: изменение видно даже
тогда, когда mtime совпал с точностью до тика часов.

Файлы маленькие, проверка — один stat на запрос. Каталог RUNTIME_DIR
должен лежать на локальной файловой системе: в Docker — именованный том,
а не папка хоста. На пробросе папки Windows через Docker Desktop атрибуты
файлов могут кешироваться, и тогда соседний воркер увидит изменение
с опозданием.

Запись — под межпроцессной блокировкой (flock в Linux, msvcrt в Windows):
прочитать свежее → изменить → записать, иначе два воркера потеряли бы
изменения друг друга или дважды засчитали один батч.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_thread_locks: dict = {}
_thread_locks_guard = threading.Lock()


def signature(path: Path) -> tuple | None:
    """Подпись файла или None, если его нет."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _thread_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _thread_locks_guard:
        lock = _thread_locks.get(key)
        if lock is None:
            lock = _thread_locks[key] = threading.Lock()
        return lock


@contextmanager
def file_lock(path: Path):
    """Эксклюзивная блокировка между процессами и потоками на время
    чтения-изменения-записи файла path. Блокируется соседний .lock-файл."""
    lock_path = path.with_name(path.name + ".lock")
    with _thread_lock(lock_path):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                        break
                    except OSError:
                        continue  # LK_LOCK сам ждёт ~10 с, потом ошибка — ждём дальше
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()


def atomic_write(path: Path, text: str) -> None:
    """Запись через временный файл: читатель видит либо старую версию,
    либо новую, но не половину."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            # Windows не даёт заменить файл, открытый другим процессом.
            # В Linux (контейнер) сюда не попадаем.
            time.sleep(0.01 * (attempt + 1))
    os.replace(tmp, path)


# ---------------------------------------------------------- метка перезагрузки

def reload_marker_path() -> Path:
    from app import config

    return config.RELOAD_MARKER_PATH


def bump_reload_marker() -> bool:
    """POST /api/reload: сигнал всем воркерам перечитать файлы данных."""
    path = reload_marker_path()
    try:
        with file_lock(path):
            atomic_write(path, f"{time.time_ns()} {os.getpid()}\n")
        return True
    except OSError:
        return False


def reload_generation() -> tuple | None:
    return signature(reload_marker_path())

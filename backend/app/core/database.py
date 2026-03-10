import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List


BASE_DIR = Path(__file__).resolve().parents[3]
PRIMARY_DB_PATH = BASE_DIR / "data_storage" / "datamind.db"
LEGACY_DB_PATH = BASE_DIR / "backend" / "data_storage" / "datamind.db"


def _resolve_db_path() -> Path:
    if PRIMARY_DB_PATH.exists() or not LEGACY_DB_PATH.exists():
        return PRIMARY_DB_PATH
    return LEGACY_DB_PATH


DB_PATH = _resolve_db_path()


@contextmanager
def _get_connection() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    """Inicializa la base de datos y crea las tablas necesarias."""
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session_ts ON messages(session_id, timestamp)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC)"
        )


def save_message(session_id: str, role: str, content: str) -> None:
    """Guarda un mensaje en la base de datos."""
    with _get_connection() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )
        conn.execute(
            """
            UPDATE sessions
            SET updated_at = CURRENT_TIMESTAMP
            WHERE session_id = ?
            """,
            (session_id,),
        )


def get_chat_history(session_id: str, limit: int = 10) -> List[Dict[str, str]]:
    """Recupera los últimos mensajes de una sesión en orden cronológico."""
    safe_limit = max(1, min(limit, 200))
    with _get_connection() as conn:
        rows = conn.execute(
            """
            SELECT role, content
            FROM messages
            WHERE session_id = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (session_id, safe_limit),
        ).fetchall()
    return [{"role": row[0], "content": row[1]} for row in reversed(rows)]


def clear_history(session_id: str) -> None:
    """Limpia el historial de una sesión."""
    with _get_connection() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def save_session(session_id: str, title: str) -> None:
    """Crea o actualiza una sesión."""
    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO sessions (session_id, title, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id) DO UPDATE SET
                title = excluded.title,
                updated_at = CURRENT_TIMESTAMP
            """,
            (session_id, title),
        )


def get_all_sessions() -> List[Dict[str, str]]:
    """Obtiene todas las sesiones ordenadas por la más reciente."""
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT session_id, title FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
    return [{"session_id": row[0], "title": row[1]} for row in rows]


def update_session_title(session_id: str, title: str) -> None:
    """Actualiza solo el título de una sesión."""
    with _get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (title, session_id),
        )


init_db()

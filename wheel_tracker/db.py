import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / 'portfolio.db'


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    with open(Path(__file__).resolve().parent / 'schema.sql', 'r', encoding='utf-8') as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()

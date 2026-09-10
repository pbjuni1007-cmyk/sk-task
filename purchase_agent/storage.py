"""SQLite owns business state. Every service mutation uses BEGIN IMMEDIATE."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

class Database:
    def __init__(self,path):
        self.path=str(path)
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.transaction() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, owner TEXT NOT NULL, version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS versions(id TEXT NOT NULL, version INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(id,version));
            CREATE TABLE IF NOT EXISTS actions(actor TEXT, action TEXT, request_id TEXT, PRIMARY KEY(actor,action));
            CREATE TABLE IF NOT EXISTS confirmations(token TEXT PRIMARY KEY, actor TEXT, thread TEXT, request_id TEXT, version INTEGER, bundle TEXT, hash TEXT, boot TEXT, consumed INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS preferences(actor TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS preference_meta(actor TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT);
            ''')
    @contextmanager
    def transaction(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally: db.close()

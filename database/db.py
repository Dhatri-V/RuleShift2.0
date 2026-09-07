import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from core.config import get_database_url


# The database URL comes from the central config layer (environment or
# .env file); it defaults to the local SQLite file for development.
DATABASE_URL = get_database_url()

@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(connection, connection_record):
    """Enforce relational constraints on app, migration, and test connections."""
    if isinstance(connection, sqlite3.Connection):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()

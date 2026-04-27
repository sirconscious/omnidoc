import psycopg2
from psycopg2.extras import RealDictCursor
from app.core.config import (
    POSTGRES_HOST, POSTGRES_PORT,
    POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
)

def get_connection():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        dbname=POSTGRES_DB
    )

def execute_query(query: str, params=None, fetch=False):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            conn.commit()
            if fetch:
                return cur.fetchall()
    finally:
        conn.close()


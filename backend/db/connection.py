import psycopg2
import psycopg2.extras
from flask import current_app, g
from psycopg2.pool import SimpleConnectionPool

_pool = None


def init_pool(app):
    """Create the connection pool once, at app startup."""
    global _pool
    _pool = SimpleConnectionPool(1, 10, dsn=app.config["DATABASE_URL"])


def _is_connection_alive(conn):
    """Run a cheap query to check the connection hasn't been dropped."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


def get_db():
    """Return a pooled connection for this request, creating one if needed."""
    if "db_conn" not in g:
        conn = _pool.getconn()

        if not _is_connection_alive(conn):
            # Connection is stale/dead — discard it and get a fresh one
            _pool.putconn(conn, close=True)
            conn = _pool.getconn()

        g.db_conn = conn
    return g.db_conn


def get_cursor():
    """Return a dict-cursor on the request's connection — rows come back as dicts."""
    conn = get_db()
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def close_db(exception=None):
    conn = g.pop("db_conn", None)
    if conn is not None:
        if exception:
            conn.rollback()
        _pool.putconn(conn)


def register_teardown(app):
    app.teardown_appcontext(close_db)

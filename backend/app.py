from flask import Flask, jsonify
from flask_cors import CORS

from config import Config
from db.connection import init_pool, register_teardown, get_cursor
from routes import auth, billing, blog, contact, geo_ip, job_status, jobs, preferences, saved_searches, staging, title_variants


def _ensure_utm_columns(app):
    """Adds the sign-up campaign columns if this database predates them (same ALTERs as
    db/schema.sql), so registration keeps working even if schema.sql hasn't been re-run.
    Never stops the app from starting."""
    from db import connection
    try:
        conn = connection._pool.getconn()
        try:
            with conn.cursor() as cur:
                for col in ("utm_source", "utm_campaign", "utm_content"):
                    cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} TEXT")
            conn.commit()
        finally:
            connection._pool.putconn(conn)
    except Exception as e:  # noqa: BLE001
        app.logger.warning("Could not ensure utm columns: %s", e)


def _ensure_blog_tables(app):
    """Creates the blog tables (db/blog.sql, all IF NOT EXISTS) so the blog works
    on an existing database without re-running schema.sql. Never stops startup."""
    import os
    from db import connection
    try:
        with open(os.path.join(os.path.dirname(__file__), "db", "blog.sql")) as f:
            ddl = f.read()
        conn = connection._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(ddl)
            conn.commit()
        finally:
            connection._pool.putconn(conn)
    except Exception as e:  # noqa: BLE001
        app.logger.warning("Could not ensure blog tables: %s", e)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(app, origins=app.config["FRONTEND_ORIGINS"], supports_credentials=True)

    init_pool(app)
    register_teardown(app)
    _ensure_utm_columns(app)
    _ensure_blog_tables(app)

    app.register_blueprint(auth.bp)
    app.register_blueprint(contact.bp)
    app.register_blueprint(jobs.bp)
    app.register_blueprint(job_status.bp)
    app.register_blueprint(saved_searches.bp)
    app.register_blueprint(preferences.bp)
    app.register_blueprint(title_variants.bp)
    app.register_blueprint(billing.bp)
    app.register_blueprint(blog.bp)
    app.register_blueprint(staging.bp)
    app.register_blueprint(geo_ip.bp)

    @app.get("/api/health")
    def health():
        try:
            cur = get_cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            return jsonify({"status": "ok", "database": "connected"})
        except Exception as e:
            return jsonify({"status": "error", "database": "disconnected", "detail": str(e)}), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
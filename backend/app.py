from flask import Flask, jsonify
from flask_cors import CORS

from config import Config
from db.connection import init_pool, register_teardown
from routes import auth, job_status, jobs, saved_searches


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(app, origins=[app.config["FRONTEND_ORIGIN"]], supports_credentials=True)

    init_pool(app)
    register_teardown(app)

    app.register_blueprint(auth.bp)
    app.register_blueprint(jobs.bp)
    app.register_blueprint(job_status.bp)
    app.register_blueprint(saved_searches.bp)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)

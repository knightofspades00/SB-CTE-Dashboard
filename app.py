"""
app.py — Application factory for the CTE Job Dashboard.
Loads configuration, registers the four route blueprints, and mounts the
root page and health-check endpoints.
"""

import os
from flask import Flask, render_template
from dotenv import load_dotenv

load_dotenv()

from config.settings import Config
from routes.schools  import schools_bp
from routes.pathways import pathways_bp
from routes.careers  import careers_bp
from routes.jobs     import jobs_bp
from routes.programs import programs_bp

def create_app():
    """Create and configure the Flask application, register blueprints, and return the app instance."""
    app = Flask(__name__)
    app.config.from_object(Config)

    app.register_blueprint(schools_bp)
    app.register_blueprint(pathways_bp)
    app.register_blueprint(careers_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(programs_bp)

    @app.route("/")
    def index():
        """Render the main dashboard page."""
        return render_template("index.html")

    @app.route("/health")
    def health():
        """Return a 200 JSON ping used by load balancers and uptime monitors."""
        return {"status": "ok"}, 200

    return app

if __name__ == "__main__":
    application = create_app()
    application.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=Config.DEBUG
    )
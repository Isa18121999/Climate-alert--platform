"""Gunicorn hook para registrar las rutas del dashboard sin modificar la aplicación Flask existente."""

def on_starting(server):
    from app import app
    from dashboard_routes import bp

    if "dashboard_routes" not in app.blueprints:
        app.register_blueprint(bp)

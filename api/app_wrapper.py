"""Entrada WSGI del dashboard: registra las rutas nuevas antes de servir Flask."""
from app import app
from dashboard_routes import bp

app.register_blueprint(bp)

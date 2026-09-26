"""WSGI 入口：gunicorn 'wsgi:app'。"""
from app import create_app

app = create_app()

#!/bin/sh
# 容器入口：默认起 HTTP 服务；`test` 子命令只跑测试后退出。
set -e

case "${1:-serve}" in
  serve)
    exec gunicorn --bind 0.0.0.0:8000 \
      --workers 1 --threads 8 --timeout 120 \
      wsgi:app
    ;;
  test)
    exec python -m pytest -q
    ;;
  *)
    exec "$@"
    ;;
esac

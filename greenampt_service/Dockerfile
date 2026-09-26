FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GA_DATA_DIR=/data

WORKDIR /app

# 先装依赖，利用层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝源码与测试
COPY app ./app
COPY tests ./tests
COPY wsgi.py pytest.ini ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# 工况档的容器内持久化位置
RUN mkdir -p /data && chmod 777 /data
VOLUME ["/data"]

# 构建镜像的同时跑一遍自动化测试：
# 残差达标、入渗率收敛到 Ks、积水时刻判定、
# 各参数单调走向、多方案并发隔离
RUN python -m pytest -q

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["serve"]

FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖（无 C 扩展，纯 Python 够用）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 Docker 缓存层
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY bot.py .
COPY pyproject.toml .
COPY plugins/ ./plugins/

# 创建数据目录（挂载点）
RUN mkdir -p /app/plugins/group_guard/data

# 暴露 FastAPI + WebSocket 端口
EXPOSE 8080

# 启动命令
CMD ["python", "bot.py"]

# 使用官方 Python 3.9 轻量镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量，防止 python 产生 pyc 文件及开启输出缓冲
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

# 安装系统时区工具并设置
RUN apt-get update && apt-get install -y tzdata \
    && ln -fs /usr/share/zoneinfo/${TZ} /etc/localtime \
    && echo ${TZ} > /etc/timezone \
    && apt-get clean

# 复制依赖清单并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源代码
COPY . .

# 创建日志存放目录
RUN mkdir -p /app/downloaded_logs

# 暴露 FastAPI 默认端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
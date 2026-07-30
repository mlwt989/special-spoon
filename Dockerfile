FROM python:3.11-slim

# 安装 FFmpeg 和中文字体（Noto Sans CJK）
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 上传/输出目录（运行时自动创建，挂载卷可持久化）
RUN mkdir -p uploads outputs fonts watermarks

EXPOSE 5000

# 单 worker + 多线程：FFmpeg 渲染是 CPU 密集型，多 worker 会抢资源
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "600", "app:app"]

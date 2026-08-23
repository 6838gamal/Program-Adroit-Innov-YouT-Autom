# Dockerfile
FROM python:3.11-slim

# تعيين متغيرات البيئة
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# تثبيت ffmpeg (مطلوب لمعالجة الفيديو)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# تعيين مجلد العمل
WORKDIR /app

# نسخ ملفات المتطلبات أولاً
COPY requirements.txt .
COPY pyproject.toml .

# تثبيت التبعيات
RUN pip install --no-cache-dir -r requirements.txt

# نسخ جميع ملفات المشروع
COPY . .

# إنشاء المجلدات المطلوبة
RUN mkdir -p /app/media /app/temp /app/exports /app/data /app/logs /app/cache /app/config

# تعيين المستخدم غير الجذري
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# تعيين المنفذ
EXPOSE 10000

# استخدام متغير PORT من البيئة (افتراضي 10000)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]

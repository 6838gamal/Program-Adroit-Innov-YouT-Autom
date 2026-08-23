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

# تعيين مجلد العمل (بدون app)
WORKDIR /app

# نسخ ملفات المتطلبات أولاً (للاستفادة من caching)
COPY requirements.txt .
COPY pyproject.toml .

# تثبيت التبعيات
RUN pip install --no-cache-dir -r requirements.txt

# نسخ جميع ملفات المشروع (main.py في الجذر مباشرة)
COPY . .

# إنشاء المجلدات المطلوبة
RUN mkdir -p /app/media /app/temp /app/exports /app/data /app/logs /app/cache /app/config

# تعيين المستخدم غير الجذري
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# تعيين المنفذ
EXPOSE 5000

# تشغيل main.py مباشرة (موجود في الجذر)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]

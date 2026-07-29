# Content Production & Publishing Platform

منصة احترافية لإنتاج ونشر المحتوى المرئي، مبنية بـ Python / FastAPI.

## تشغيل المشروع

```bash
python main.py
```

المنصة تعمل على المنفذ **5000**.

## الهيكل المعماري

```
shared/          ← Shared Kernel (Base entities, Value objects, Port contracts)
core/            ← Core Engine (Domain models, Production pipeline)
publishing/      ← Publishing Engine (Platform-agnostic publishing logic)
infrastructure/  ← Infrastructure (SQLAlchemy, Repositories, Storage, Event bus)
plugins/         ← Plugin Layer (FFmpeg renderer, Voice engines, Platform publishers)
application/     ← Application Layer (Use cases / Services)
interfaces/      ← Interfaces (FastAPI routes, Schemas, WebSocket, Web UI)
scheduler/       ← APScheduler jobs
templates/       ← Jinja2 HTML templates
config/          ← Settings & plugin_config.yaml
architecture/    ← Full engineering architecture document
```

## وثيقة الهندسة

راجع `architecture/ARCHITECTURE.md` للمواصفات الكاملة.

## التقنيات

- Python 3.11 + FastAPI + Uvicorn
- SQLAlchemy 2 (async) + SQLite (MVP) → PostgreSQL (لاحقاً)
- Jinja2 + HTMX + Alpine.js + Tailwind CSS
- FFmpeg (عبر Renderer Plugin فقط)
- APScheduler
- WebSocket (تقدم الرندر والنشر لحظياً)

## المنافذ

| Port | الاستخدام |
|------|-----------|
| 5000 | FastAPI Web + API |

## APIs

- `GET /api/v1/health` — فحص صحة النظام
- `GET /api/v1/projects` — قائمة المشاريع
- `POST /api/v1/projects` — إنشاء مشروع
- `POST /api/v1/production/render` — بدء الرندر
- `GET /api/v1/production/jobs` — مهام الرندر
- `POST /api/v1/assets` — رفع أصل
- `GET /api/v1/publishing/platforms` — المنصات
- `POST /api/v1/publishing/accounts` — ربط حساب
- `POST /api/v1/publishing/publish` — نشر محتوى
- `WS /ws/render/{job_id}` — تقدم الرندر (WebSocket)

## توثيق تفاعلي

`/docs` — Swagger UI  
`/redoc` — ReDoc

## إضافة منصة نشر جديدة

1. أنشئ `plugins/publishers/<platform>/<platform>_plugin.py` تُنفذ `PublisherPort`
2. أضف سطراً في `config/plugin_config.yaml`
3. أضف سجلاً في جدول `publishing_platforms`

لا تعديل في Core أبداً.

## User preferences

- اللغة: العربية
- بنية: Clean Architecture + Plugin System
- قاعدة البيانات: SQLite (MVP) → PostgreSQL لاحقاً

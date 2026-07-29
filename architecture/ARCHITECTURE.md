# وثيقة الهندسة المعمارية
# Content Production & Publishing Platform

**الإصدار:** 1.0.0  
**التاريخ:** 2026-07-29  
**الحالة:** MVP Architecture

---

## الفهرس

1. [تحليل المتطلبات](#1-تحليل-المتطلبات)
2. [التصميم المعماري](#2-التصميم-المعماري)
3. [هيكل المجلدات](#3-هيكل-المجلدات)
4. [تصميم قاعدة البيانات](#4-تصميم-قاعدة-البيانات)
5. [تصميم REST APIs](#5-تصميم-rest-apis)
6. [تصميم Core Engine](#6-تصميم-core-engine)
7. [تصميم Timeline Engine](#7-تصميم-timeline-engine)
8. [تصميم Rendering Engine](#8-تصميم-rendering-engine)
9. [تصميم Publishing Engine](#9-تصميم-publishing-engine)
10. [تصميم Plugin System](#10-تصميم-plugin-system)
11. [تصميم واجهة FastAPI](#11-تصميم-واجهة-fastapi)
12. [تصميم نظام المهام المجدولة](#12-تصميم-نظام-المهام-المجدولة)
13. [خطة التنفيذ](#13-خطة-التنفيذ)
14. [الأداء والمعالجة المتوازية](#14-الأداء-والمعالجة-المتوازية)
15. [إضافة منصات جديدة](#15-إضافة-منصات-جديدة)

---

## 1. تحليل المتطلبات

### 1.1 المتطلبات الوظيفية (Functional Requirements)

#### إدارة المشاريع
- FR-01: إنشاء مشاريع فيديو جديدة مع عنوان، وصف، نص، وسوم، أصول
- FR-02: تحرير المشاريع في أي مرحلة من مراحل الإنتاج
- FR-03: نسخ المشاريع وتعديلها
- FR-04: حذف المشاريع مع أصولها
- FR-05: عرض قائمة المشاريع مع حالتها الحالية
- FR-06: البحث والتصفية في المشاريع

#### محرك الإنتاج (Production Engine)
- FR-10: معالجة النصوص وتقسيمها إلى مشاهد
- FR-11: إنشاء Timeline تلقائي من المشروع
- FR-12: توليد الصوت من النص عبر محركات متعددة (TTS plugins)
- FR-13: توليد الترجمة (SRT / ASS / Burned)
- FR-14: تعيين الأصول للمشاهد
- FR-15: تطبيق الطبقات (Video, Image, Text, Logo, Overlay, Audio, Music)
- FR-16: تطبيق المؤثرات (Fade, Zoom, Pan, Ken Burns, إلخ)
- FR-17: تطبيق الانتقالات بين المشاهد
- FR-18: Render الفيديو النهائي
- FR-19: ترميز الفيديو بصيغ متعددة (MP4, MOV, AVI, GIF, WEBM)
- FR-20: توليد الصورة المصغرة (Thumbnail)
- FR-21: تصدير الفيديو بنسب أبعاد مختلفة من نفس المشروع

#### مكتبة الأصول (Assets Library)
- FR-30: رفع وتخزين الصور، الفيديوهات، الموسيقى، الخطوط، الأيقونات، الشعارات
- FR-31: تنظيم الأصول في تصنيفات
- FR-32: مشاركة الأصول بين جميع المشاريع
- FR-33: البحث والتصفية في مكتبة الأصول
- FR-34: معاينة الأصول

#### محرك النشر (Publishing Engine)
- FR-40: إدارة حسابات المنصات المتعددة
- FR-41: جدولة النشر (فوري / مجدول / متكرر)
- FR-42: رفع المحتوى إلى المنصات
- FR-43: متابعة حالة النشر في الوقت الفعلي
- FR-44: إعادة المحاولة تلقائياً عند الفشل
- FR-45: تسجيل جميع عمليات النشر
- FR-46: دعم منصات متعددة عبر Plugin System

#### الواجهة (Dashboard)
- FR-50: لوحة تحكم رئيسية مع إحصاءات
- FR-51: محرر Timeline تفاعلي
- FR-52: عرض تقدم العمليات بالوقت الفعلي عبر WebSocket
- FR-53: إدارة قائمة انتظار الرندر والنشر
- FR-54: إدارة القوالب
- FR-55: إدارة المنصات المتصلة
- FR-56: سجل العمليات والأحداث
- FR-57: Analytics

### 1.2 المتطلبات غير الوظيفية (Non-Functional Requirements)

#### الأداء
- NFR-01: وقت استجابة API أقل من 200ms للعمليات العادية
- NFR-02: دعم معالجة متوازية لعمليات الرندر
- NFR-03: Streaming للبيانات الكبيرة (فيديوهات، أصول)
- NFR-04: WebSocket لتحديثات الوقت الفعلي

#### القابلية للتوسع
- NFR-10: Plugin Architecture بحيث لا يحتاج Core لتعديل عند إضافة أي منصة أو محرك
- NFR-11: دعم مستقبلي للـ multi-tenancy (SaaS)
- NFR-12: الانتقال من SQLite إلى PostgreSQL دون تعديل الكود
- NFR-13: بنية قابلة للتحول إلى Microservices لاحقاً

#### الموثوقية
- NFR-20: Retry Policy لعمليات النشر
- NFR-21: Transaction safety لقاعدة البيانات
- NFR-22: تسجيل جميع الأخطاء والأحداث
- NFR-23: Health Checks دورية للمنصات المتصلة

#### الأمان
- NFR-30: تشفير بيانات اعتماد المنصات
- NFR-31: Input Validation عبر Pydantic
- NFR-32: CSRF Protection
- NFR-33: Rate Limiting

#### قابلية الاختبار
- NFR-40: اختبارات وحدة لكل Component
- NFR-41: اختبارات تكامل للـ Pipelines
- NFR-42: Mocking للمنصات الخارجية

---

## 2. التصميم المعماري

### 2.1 نظرة عامة

```
┌─────────────────────────────────────────────────────────────────┐
│                        INTERFACES LAYER                          │
│   FastAPI + Jinja2 + HTMX + Alpine.js + Tailwind CSS            │
│   REST API  │  WebSocket  │  Web Dashboard                      │
└─────────────────────────┬───────────────────────────────────────┘
                           │
┌─────────────────────────▼───────────────────────────────────────┐
│                     APPLICATION LAYER                            │
│   Project Service  │  Production Service  │  Publishing Service  │
│   Asset Service    │  Scheduler Service   │  Analytics Service   │
└──────────┬──────────────────┬──────────────────────┬────────────┘
           │                  │                       │
┌──────────▼──────────┐  ┌───▼──────────────┐  ┌────▼────────────┐
│    CORE ENGINE      │  │  TIMELINE ENGINE │  │ PUBLISHING ENG. │
│  Domain Models      │  │  Timeline        │  │  Publisher Ports │
│  Business Rules     │  │  Tracks          │  │  Queue Manager   │
│  Production Pipeline│  │  Scenes          │  │  Retry Policy    │
│  Plugin Ports       │  │  Layers          │  │  Account Manager │
└──────────┬──────────┘  └───┬──────────────┘  └────┬────────────┘
           │                  │                       │
┌──────────▼──────────────────▼───────────────────────▼────────────┐
│                     INFRASTRUCTURE LAYER                          │
│   SQLAlchemy ORM   │  Repositories  │  File Storage               │
│   Alembic Migration│  Cache         │  Message Queue              │
└─────────────────────────────────────────────────────────────────┘
                           │
┌─────────────────────────▼───────────────────────────────────────┐
│                       PLUGIN LAYER                               │
│  Voice Plugins      │  Renderer Plugin  │  Publisher Plugins      │
│  Effect Plugins     │  Transition Plugin│  Storage Plugins         │
│  Subtitle Plugins   │  Exporter Plugins │  Template Plugins        │
└─────────────────────────────────────────────────────────────────┘
                           │
┌─────────────────────────▼───────────────────────────────────────┐
│                     SHARED KERNEL                                │
│   Base Entities   │  Value Objects  │  Domain Events              │
│   Common Types    │  Exceptions     │  Interfaces/Ports            │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 مسؤولية كل طبقة

#### Shared Kernel
المسؤولية: الأنواع والعقود والأحداث المشتركة بين جميع الطبقات.
- `BaseEntity`: كيان أساسي بـ UUID وتواريخ الإنشاء والتعديل
- `ValueObjects`: أنواع القيم (Resolution, AspectRatio, Duration, etc.)
- `DomainEvents`: أحداث النطاق (ProjectCreated, RenderStarted, PublishCompleted)
- `Ports/Interfaces`: عقود Plugin System
- `Exceptions`: استثناءات النطاق المشتركة
- `Result[T, E]`: نمط النتيجة لمعالجة الأخطاء بدون استثناءات

#### Core Engine
المسؤولية: منطق الأعمال الصرف، لا يعتمد على أي Infrastructure.
- Domain Models (Project, Timeline, Scene, Layer, Asset)
- Production Pipeline (تسلسل الخطوات من النص للفيديو)
- Plugin Ports (عقود Voice, Renderer, Exporter, Effect, Transition)
- Business Rules & Invariants

#### Timeline Engine
المسؤولية: إدارة بنية المشروع المؤقتة.
- Timeline: الخط الزمني الرئيسي للمشروع
- Tracks: مسارات (Audio, Video, Subtitle, Animation, Overlay, Music)
- Scenes: المشاهد والتحكم في توقيتها
- Layers: الطبقات داخل كل مشهد
- Markers: نقاط مرجعية على الخط الزمني

#### Application Layer
المسؤولية: تنسيق العمليات وتدفق البيانات بين Core وInfrastructure.
- Use Cases (كل عملية = Use Case منفصل)
- DTOs (Data Transfer Objects)
- Application Services
- Event Handlers

#### Infrastructure Layer
المسؤولية: التفاصيل التقنية (قاعدة البيانات، الملفات، الشبكة).
- Repository Implementations (SQLAlchemy)
- File Storage Adapters
- External API Clients
- Cache Implementation

#### Plugin Layer
المسؤولية: التوسعة الخارجية. كل Plugin ينفذ Port محدد من Core.
- اكتشاف تلقائي عبر Entry Points أو Config
- لا يُسمح لأي Plugin بتعديل Core

#### Interfaces Layer
المسؤولية: واجهة المستخدم والـ APIs.
- FastAPI Routers
- WebSocket Handlers
- Jinja2 Templates
- Dependency Injection Setup

---

## 3. هيكل المجلدات

```
content_platform/
│
├── main.py                          # Entry point
├── pyproject.toml                   # Dependencies & config
├── alembic.ini
├── .env.example
│
├── shared/                          # SHARED KERNEL
│   ├── __init__.py
│   ├── base_entity.py               # BaseEntity with UUID, timestamps
│   ├── value_objects.py             # Resolution, Duration, AspectRatio, etc.
│   ├── domain_events.py             # DomainEvent base + all events
│   ├── result.py                    # Result[T, E] monad
│   ├── exceptions.py                # Domain exceptions
│   └── ports/                       # Plugin contracts
│       ├── __init__.py
│       ├── voice_port.py
│       ├── renderer_port.py
│       ├── exporter_port.py
│       ├── publisher_port.py
│       ├── effect_port.py
│       ├── transition_port.py
│       ├── subtitle_port.py
│       ├── storage_port.py
│       ├── template_port.py
│       └── animation_port.py
│
├── core/                            # CORE ENGINE
│   ├── __init__.py
│   ├── domain/
│   │   ├── project/
│   │   │   ├── project.py           # Project aggregate root
│   │   │   ├── project_status.py    # ProjectStatus enum
│   │   │   └── output_profile.py    # OutputProfile (16:9, 9:16, etc.)
│   │   ├── timeline/
│   │   │   ├── timeline.py          # Timeline aggregate
│   │   │   ├── track.py             # Track entity
│   │   │   ├── scene.py             # Scene entity
│   │   │   ├── layer.py             # Layer base + subtypes
│   │   │   └── marker.py            # Timeline markers
│   │   ├── asset/
│   │   │   ├── asset.py             # Asset entity
│   │   │   └── asset_type.py        # AssetType enum
│   │   ├── template/
│   │   │   ├── template.py          # Template entity
│   │   │   └── template_preset.py
│   │   ├── voice/
│   │   │   └── voice_config.py      # VoiceConfig value object
│   │   ├── effect/
│   │   │   └── effect.py            # Effect entity
│   │   ├── transition/
│   │   │   └── transition.py        # Transition entity
│   │   └── rendering/
│   │       ├── render_job.py        # RenderJob aggregate
│   │       └── export_job.py        # ExportJob entity
│   │
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── production_pipeline.py   # Orchestrates full pipeline
│   │   ├── stages/
│   │   │   ├── script_processor.py
│   │   │   ├── scene_detector.py
│   │   │   ├── timeline_generator.py
│   │   │   ├── voice_generator.py
│   │   │   ├── subtitle_generator.py
│   │   │   ├── asset_assigner.py
│   │   │   ├── layer_compositor.py
│   │   │   ├── effects_applier.py
│   │   │   ├── transitions_applier.py
│   │   │   ├── renderer.py
│   │   │   ├── encoder.py
│   │   │   ├── thumbnail_generator.py
│   │   │   └── exporter.py
│   │   └── pipeline_context.py      # Context passed through stages
│   │
│   └── repositories/                # Repository Interfaces (not implementations)
│       ├── project_repository.py
│       ├── timeline_repository.py
│       ├── asset_repository.py
│       ├── template_repository.py
│       ├── render_job_repository.py
│       └── export_job_repository.py
│
├── publishing/                      # PUBLISHING ENGINE
│   ├── __init__.py
│   ├── domain/
│   │   ├── publisher_account.py     # PublisherAccount aggregate
│   │   ├── publishing_platform.py   # Platform config entity
│   │   ├── publishing_profile.py    # Platform-specific profile
│   │   ├── publishing_job.py        # PublishingJob aggregate
│   │   ├── publishing_queue.py      # Queue management
│   │   └── schedule.py              # Schedule entity
│   ├── services/
│   │   ├── publishing_service.py
│   │   ├── account_manager.py
│   │   ├── retry_service.py
│   │   └── platform_registry.py    # Plugin registry for publishers
│   └── repositories/
│       ├── account_repository.py
│       ├── platform_repository.py
│       └── publishing_job_repository.py
│
├── application/                     # APPLICATION LAYER
│   ├── __init__.py
│   ├── projects/
│   │   ├── create_project.py        # CreateProjectUseCase
│   │   ├── update_project.py
│   │   ├── delete_project.py
│   │   ├── get_project.py
│   │   └── list_projects.py
│   ├── production/
│   │   ├── start_production.py      # StartProductionUseCase
│   │   ├── get_render_status.py
│   │   └── cancel_render.py
│   ├── assets/
│   │   ├── upload_asset.py
│   │   ├── list_assets.py
│   │   └── delete_asset.py
│   ├── publishing/
│   │   ├── publish_content.py
│   │   ├── schedule_publish.py
│   │   └── get_publish_status.py
│   ├── timeline/
│   │   ├── update_timeline.py
│   │   └── get_timeline.py
│   └── dto/
│       ├── project_dto.py
│       ├── timeline_dto.py
│       ├── asset_dto.py
│       └── publishing_dto.py
│
├── infrastructure/                  # INFRASTRUCTURE LAYER
│   ├── __init__.py
│   ├── database/
│   │   ├── session.py               # SQLAlchemy engine & session
│   │   ├── models/                  # ORM Models
│   │   │   ├── project_model.py
│   │   │   ├── timeline_model.py
│   │   │   ├── scene_model.py
│   │   │   ├── layer_model.py
│   │   │   ├── asset_model.py
│   │   │   ├── template_model.py
│   │   │   ├── render_job_model.py
│   │   │   ├── export_job_model.py
│   │   │   ├── publisher_account_model.py
│   │   │   ├── publishing_job_model.py
│   │   │   ├── schedule_model.py
│   │   │   ├── log_model.py
│   │   │   ├── plugin_model.py
│   │   │   └── analytics_model.py
│   │   └── migrations/              # Alembic migrations
│   ├── repositories/                # Repository Implementations
│   │   ├── sql_project_repository.py
│   │   ├── sql_timeline_repository.py
│   │   ├── sql_asset_repository.py
│   │   ├── sql_render_job_repository.py
│   │   ├── sql_publishing_job_repository.py
│   │   └── sql_account_repository.py
│   ├── storage/
│   │   ├── local_storage.py         # LocalStorageAdapter
│   │   └── s3_storage.py            # S3StorageAdapter (future)
│   ├── cache/
│   │   └── memory_cache.py
│   └── event_bus/
│       └── in_memory_event_bus.py
│
├── plugins/                         # PLUGIN LAYER
│   ├── __init__.py
│   ├── registry.py                  # PluginRegistry (discovery & registration)
│   ├── voice/
│   │   ├── piper_plugin.py          # PiperVoicePlugin
│   │   ├── coqui_plugin.py          # CoquiVoicePlugin
│   │   └── kokoro_plugin.py         # KokoroVoicePlugin
│   ├── renderer/
│   │   └── ffmpeg_renderer.py       # FFmpegRendererPlugin
│   ├── exporter/
│   │   └── ffmpeg_exporter.py       # FFmpegExporterPlugin
│   ├── publishers/
│   │   └── youtube/
│   │       ├── __init__.py
│   │       ├── youtube_plugin.py    # YouTubePublisherPlugin
│   │       ├── youtube_auth.py
│   │       ├── youtube_profile.py   # YouTube platform constraints
│   │       └── youtube_uploader.py
│   ├── effects/
│   │   ├── fade_effect.py
│   │   ├── zoom_effect.py
│   │   ├── pan_effect.py
│   │   ├── ken_burns_effect.py
│   │   └── blur_effect.py
│   ├── transitions/
│   │   ├── fade_transition.py
│   │   ├── crossfade_transition.py
│   │   ├── slide_transition.py
│   │   └── zoom_transition.py
│   ├── subtitle/
│   │   ├── srt_subtitle.py
│   │   ├── ass_subtitle.py
│   │   └── burned_subtitle.py
│   └── templates/
│       ├── minimal_template.py
│       └── professional_template.py
│
├── interfaces/                      # INTERFACES LAYER
│   ├── __init__.py
│   ├── api/
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── projects.py          # /api/v1/projects
│   │   │   ├── timeline.py          # /api/v1/timeline
│   │   │   ├── assets.py            # /api/v1/assets
│   │   │   ├── production.py        # /api/v1/production
│   │   │   ├── publishing.py        # /api/v1/publishing
│   │   │   ├── templates.py         # /api/v1/templates
│   │   │   ├── voices.py            # /api/v1/voices
│   │   │   ├── platforms.py         # /api/v1/platforms
│   │   │   ├── schedules.py         # /api/v1/schedules
│   │   │   ├── analytics.py         # /api/v1/analytics
│   │   │   └── health.py            # /api/v1/health
│   │   └── router.py                # Aggregate all routers
│   ├── websocket/
│   │   ├── render_progress.py       # WS: render progress
│   │   └── publish_progress.py      # WS: publish progress
│   ├── web/
│   │   ├── routes.py                # Jinja2 page routes
│   │   └── dependencies.py          # FastAPI DI setup
│   └── schemas/                     # Pydantic request/response schemas
│       ├── project_schemas.py
│       ├── timeline_schemas.py
│       ├── asset_schemas.py
│       ├── production_schemas.py
│       ├── publishing_schemas.py
│       └── common_schemas.py
│
├── scheduler/                       # SCHEDULER
│   ├── __init__.py
│   ├── scheduler.py                 # APScheduler setup
│   ├── jobs/
│   │   ├── publish_job.py
│   │   ├── retry_job.py
│   │   └── cleanup_job.py
│   └── scheduler_service.py
│
├── templates/                       # Jinja2 HTML Templates
│   ├── base.html
│   ├── dashboard.html
│   ├── projects/
│   │   ├── list.html
│   │   ├── detail.html
│   │   └── create.html
│   ├── timeline/
│   │   └── editor.html
│   ├── assets/
│   │   └── library.html
│   ├── publishing/
│   │   ├── queue.html
│   │   └── platforms.html
│   ├── render/
│   │   └── queue.html
│   ├── templates_page/
│   │   └── list.html
│   ├── schedules/
│   │   └── list.html
│   ├── analytics/
│   │   └── dashboard.html
│   ├── settings/
│   │   └── index.html
│   └── components/                  # HTMX partial templates
│       ├── project_card.html
│       ├── asset_card.html
│       ├── progress_bar.html
│       └── notification.html
│
├── static/
│   ├── css/
│   │   └── tailwind.css
│   ├── js/
│   │   ├── app.js
│   │   └── timeline_editor.js
│   └── icons/
│
├── config/
│   ├── __init__.py
│   ├── settings.py                  # Pydantic Settings
│   └── plugin_config.yaml           # Enabled plugins config
│
└── tests/
    ├── unit/
    │   ├── core/
    │   ├── timeline/
    │   └── publishing/
    ├── integration/
    │   ├── api/
    │   └── pipeline/
    └── conftest.py
```

---

## 4. تصميم قاعدة البيانات

### 4.1 ERD (Entity Relationship Diagram)

```
PROJECTS ────────────── TIMELINES
    │                       │
    │                   TRACKS
    │                       │
    │                   SCENES
    │                       │
    │                   LAYERS
    │
    ├── RENDER_JOBS
    │       │
    │   EXPORT_JOBS
    │
    ├── OUTPUT_PROFILES
    │
    └── PUBLISHING_JOBS
            │
        PUBLISHING_QUEUE
            │
    PUBLISHER_ACCOUNTS ── PUBLISHING_PLATFORMS
                                │
                        PUBLISHING_PROFILES
                        PLATFORM_SETTINGS

ASSETS ──────── ASSET_TAGS
    │
ASSET_CATEGORIES

TEMPLATES ────── TEMPLATE_PRESETS

VOICES

EFFECTS ─────── EFFECT_PRESETS
TRANSITIONS ─── TRANSITION_PRESETS
ANIMATIONS

SCHEDULES ────── PUBLISHING_JOBS

PLUGINS ─────── PLUGIN_CONFIGS

LOGS
ANALYTICS_EVENTS
NOTIFICATIONS
```

### 4.2 الجداول والعلاقات

#### projects
```sql
CREATE TABLE projects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       VARCHAR(500) NOT NULL,
    description TEXT,
    script      TEXT,
    tags        JSON,           -- ["tag1", "tag2"]
    status      VARCHAR(50) NOT NULL DEFAULT 'draft',
                                -- draft|in_production|rendered|published|failed
    template_id UUID REFERENCES templates(id),
    logo_asset_id UUID REFERENCES assets(id),
    brand_colors JSON,          -- {"primary": "#fff", "secondary": "#000"}
    settings    JSON,           -- project-level overrides
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    deleted_at  TIMESTAMP       -- soft delete
);
```

#### timelines
```sql
CREATE TABLE timelines (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    duration    FLOAT NOT NULL DEFAULT 0.0,   -- seconds
    fps         INTEGER NOT NULL DEFAULT 30,
    resolution  JSON NOT NULL,                -- {"width": 1920, "height": 1080}
    settings    JSON,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### tracks
```sql
CREATE TABLE tracks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timeline_id UUID NOT NULL REFERENCES timelines(id) ON DELETE CASCADE,
    type        VARCHAR(50) NOT NULL,
                -- video|audio|subtitle|animation|overlay|music|logo
    name        VARCHAR(200),
    position    INTEGER NOT NULL DEFAULT 0,
    is_muted    BOOLEAN NOT NULL DEFAULT FALSE,
    is_locked   BOOLEAN NOT NULL DEFAULT FALSE,
    settings    JSON,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### scenes
```sql
CREATE TABLE scenes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    track_id    UUID NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    timeline_id UUID NOT NULL REFERENCES timelines(id),
    name        VARCHAR(200),
    start_time  FLOAT NOT NULL DEFAULT 0.0,
    end_time    FLOAT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    transition_in  JSON,        -- {type: "fade", duration: 0.5}
    transition_out JSON,
    settings    JSON,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### layers
```sql
CREATE TABLE layers (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scene_id    UUID NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    type        VARCHAR(50) NOT NULL,
                -- video|image|text|subtitle|logo|overlay|audio|music|animation
    name        VARCHAR(200),
    position    INTEGER NOT NULL DEFAULT 0,
    start_time  FLOAT NOT NULL DEFAULT 0.0,
    end_time    FLOAT,
    asset_id    UUID REFERENCES assets(id),
    properties  JSON NOT NULL DEFAULT '{}',
                -- text content, position, size, color, font, opacity, etc.
    effects     JSON DEFAULT '[]',  -- [{type: "fade", params: {...}}]
    animations  JSON DEFAULT '[]',  -- keyframe animations
    is_visible  BOOLEAN NOT NULL DEFAULT TRUE,
    z_index     INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### assets
```sql
CREATE TABLE assets (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         VARCHAR(500) NOT NULL,
    type         VARCHAR(50) NOT NULL,
                 -- image|video|audio|font|icon|logo|transition|animation|
                 --   background|sticker|overlay
    file_path    VARCHAR(1000) NOT NULL,
    file_size    BIGINT,
    mime_type    VARCHAR(100),
    duration     FLOAT,          -- for audio/video
    width        INTEGER,
    height       INTEGER,
    metadata     JSON DEFAULT '{}',
    tags         JSON DEFAULT '[]',
    category_id  UUID REFERENCES asset_categories(id),
    is_global    BOOLEAN NOT NULL DEFAULT TRUE,
    project_id   UUID REFERENCES projects(id),  -- NULL = global asset
    created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE asset_categories (
    id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name    VARCHAR(200) NOT NULL UNIQUE,
    parent_id UUID REFERENCES asset_categories(id)
);
```

#### templates
```sql
CREATE TABLE templates (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(200) NOT NULL,
    description TEXT,
    thumbnail   VARCHAR(1000),
    settings    JSON NOT NULL DEFAULT '{}',
                -- colors, fonts, text_positions, logo_position,
                --   resolution, transitions, effects, subtitle_style,
                --   animation_presets, camera_movement
    is_builtin  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### voices
```sql
CREATE TABLE voices (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(200) NOT NULL,
    plugin      VARCHAR(100) NOT NULL,   -- piper|coqui|kokoro
    language    VARCHAR(20),
    gender      VARCHAR(20),
    config      JSON NOT NULL DEFAULT '{}',
    sample_url  VARCHAR(1000),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### render_jobs
```sql
CREATE TABLE render_jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   UUID NOT NULL REFERENCES projects(id),
    status       VARCHAR(50) NOT NULL DEFAULT 'pending',
                 -- pending|queued|processing|completed|failed|cancelled
    renderer     VARCHAR(100) NOT NULL DEFAULT 'ffmpeg',
    progress     FLOAT NOT NULL DEFAULT 0.0,   -- 0-100
    output_path  VARCHAR(1000),
    error_message TEXT,
    settings     JSON DEFAULT '{}',
    started_at   TIMESTAMP,
    completed_at TIMESTAMP,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### export_jobs
```sql
CREATE TABLE export_jobs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    render_job_id  UUID NOT NULL REFERENCES render_jobs(id),
    project_id     UUID NOT NULL REFERENCES projects(id),
    format         VARCHAR(20) NOT NULL,    -- mp4|mov|avi|gif|webm
    aspect_ratio   VARCHAR(20) NOT NULL,    -- 16:9|9:16|1:1|4:5
    resolution     JSON NOT NULL,
    output_path    VARCHAR(1000),
    file_size      BIGINT,
    status         VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at   TIMESTAMP
);
```

#### publisher_accounts
```sql
CREATE TABLE publisher_accounts (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         VARCHAR(200) NOT NULL,
    platform_id  UUID NOT NULL REFERENCES publishing_platforms(id),
    credentials  TEXT NOT NULL,    -- encrypted JSON
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    last_verified TIMESTAMP,
    metadata     JSON DEFAULT '{}',
    created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### publishing_platforms
```sql
CREATE TABLE publishing_platforms (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(100) NOT NULL UNIQUE,  -- youtube|tiktok|instagram|...
    display_name  VARCHAR(200) NOT NULL,
    plugin        VARCHAR(100) NOT NULL,
    constraints   JSON NOT NULL DEFAULT '{}',
                  -- max_duration, max_file_size, supported_formats,
                  --   thumbnail_requirements, supported_aspect_ratios
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### publishing_profiles
```sql
CREATE TABLE publishing_profiles (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         VARCHAR(200) NOT NULL,
    account_id   UUID NOT NULL REFERENCES publisher_accounts(id),
    platform_id  UUID NOT NULL REFERENCES publishing_platforms(id),
    settings     JSON NOT NULL DEFAULT '{}',
                 -- default_privacy, default_category, default_tags,
                 --   scheduling_preferences
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### publishing_jobs
```sql
CREATE TABLE publishing_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id),
    export_job_id   UUID REFERENCES export_jobs(id),
    account_id      UUID NOT NULL REFERENCES publisher_accounts(id),
    profile_id      UUID REFERENCES publishing_profiles(id),
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',
                    -- pending|scheduled|queued|uploading|processing|
                    --   published|failed|cancelled
    platform_post_id VARCHAR(500),  -- ID returned by platform
    platform_url     VARCHAR(1000),
    metadata        JSON DEFAULT '{}',  -- title, description, tags, privacy
    error_message   TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    max_retries     INTEGER NOT NULL DEFAULT 3,
    scheduled_at    TIMESTAMP,
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### schedules
```sql
CREATE TABLE schedules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(200),
    project_id      UUID NOT NULL REFERENCES projects(id),
    account_id      UUID NOT NULL REFERENCES publisher_accounts(id),
    schedule_type   VARCHAR(50) NOT NULL,   -- immediate|once|recurring
    cron_expression VARCHAR(100),            -- for recurring
    scheduled_at    TIMESTAMP,               -- for once
    settings        JSON DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at     TIMESTAMP,
    next_run_at     TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### logs
```sql
CREATE TABLE logs (
    id          BIGSERIAL PRIMARY KEY,
    level       VARCHAR(20) NOT NULL,   -- debug|info|warning|error|critical
    category    VARCHAR(100),           -- production|publishing|system|api
    message     TEXT NOT NULL,
    context     JSON DEFAULT '{}',
    project_id  UUID REFERENCES projects(id),
    job_id      UUID,                   -- render or publish job
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_logs_created ON logs(created_at DESC);
CREATE INDEX idx_logs_project ON logs(project_id);
```

#### plugins
```sql
CREATE TABLE plugins (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(200) NOT NULL UNIQUE,
    type        VARCHAR(100) NOT NULL,
    version     VARCHAR(50),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    config      JSON DEFAULT '{}',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### analytics_events
```sql
CREATE TABLE analytics_events (
    id          BIGSERIAL PRIMARY KEY,
    event_type  VARCHAR(100) NOT NULL,
    project_id  UUID REFERENCES projects(id),
    platform    VARCHAR(100),
    data        JSON DEFAULT '{}',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### notifications
```sql
CREATE TABLE notifications (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type        VARCHAR(100) NOT NULL,
    title       VARCHAR(500) NOT NULL,
    message     TEXT,
    is_read     BOOLEAN NOT NULL DEFAULT FALSE,
    data        JSON DEFAULT '{}',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

## 5. تصميم REST APIs

### المبادئ العامة
- Base URL: `/api/v1`
- Content-Type: `application/json`
- التوثيق: OpenAPI 3.0 تلقائي عبر FastAPI
- الترقيم: Cursor-based pagination
- الأخطاء: RFC 7807 Problem Details

### 5.1 Projects API

```
GET    /api/v1/projects                 # List projects (with pagination & filters)
POST   /api/v1/projects                 # Create project
GET    /api/v1/projects/{id}            # Get project details
PUT    /api/v1/projects/{id}            # Update project
DELETE /api/v1/projects/{id}            # Delete project (soft)
POST   /api/v1/projects/{id}/duplicate  # Duplicate project
GET    /api/v1/projects/{id}/status     # Get production status
```

### 5.2 Timeline API

```
GET    /api/v1/projects/{id}/timeline          # Get full timeline
PUT    /api/v1/projects/{id}/timeline          # Update timeline settings
POST   /api/v1/projects/{id}/timeline/tracks   # Add track
DELETE /api/v1/projects/{id}/timeline/tracks/{track_id}
POST   /api/v1/projects/{id}/timeline/scenes   # Add scene
PUT    /api/v1/projects/{id}/timeline/scenes/{scene_id}
DELETE /api/v1/projects/{id}/timeline/scenes/{scene_id}
POST   /api/v1/projects/{id}/timeline/scenes/{scene_id}/layers
PUT    /api/v1/projects/{id}/timeline/scenes/{scene_id}/layers/{layer_id}
DELETE /api/v1/projects/{id}/timeline/scenes/{scene_id}/layers/{layer_id}
```

### 5.3 Production API

```
POST   /api/v1/production/render           # Start render job
GET    /api/v1/production/jobs             # List render jobs
GET    /api/v1/production/jobs/{id}        # Get render job status
DELETE /api/v1/production/jobs/{id}        # Cancel render job
POST   /api/v1/production/jobs/{id}/export # Start export from render
GET    /api/v1/production/exports          # List export jobs
GET    /api/v1/production/exports/{id}     # Get export status
```

### 5.4 Assets API

```
GET    /api/v1/assets                  # List assets (with filters)
POST   /api/v1/assets                  # Upload asset
GET    /api/v1/assets/{id}             # Get asset
DELETE /api/v1/assets/{id}             # Delete asset
GET    /api/v1/assets/categories       # List categories
POST   /api/v1/assets/categories       # Create category
```

### 5.5 Templates API

```
GET    /api/v1/templates               # List templates
POST   /api/v1/templates               # Create template
GET    /api/v1/templates/{id}          # Get template
PUT    /api/v1/templates/{id}          # Update template
DELETE /api/v1/templates/{id}          # Delete template
POST   /api/v1/templates/{id}/apply/{project_id}  # Apply to project
```

### 5.6 Voices API

```
GET    /api/v1/voices                  # List available voices
GET    /api/v1/voices/{id}             # Get voice
POST   /api/v1/voices/{id}/preview     # Generate preview sample
```

### 5.7 Publishing API

```
GET    /api/v1/publishing/platforms    # List platforms
GET    /api/v1/publishing/accounts     # List accounts
POST   /api/v1/publishing/accounts     # Connect account
DELETE /api/v1/publishing/accounts/{id}
POST   /api/v1/publishing/publish      # Publish content
GET    /api/v1/publishing/jobs         # List publishing jobs
GET    /api/v1/publishing/jobs/{id}    # Get job status
DELETE /api/v1/publishing/jobs/{id}    # Cancel job
GET    /api/v1/publishing/queue        # Get publishing queue
POST   /api/v1/publishing/jobs/{id}/retry  # Manual retry
```

### 5.8 Schedules API

```
GET    /api/v1/schedules               # List schedules
POST   /api/v1/schedules               # Create schedule
GET    /api/v1/schedules/{id}          # Get schedule
PUT    /api/v1/schedules/{id}          # Update schedule
DELETE /api/v1/schedules/{id}          # Delete schedule
PUT    /api/v1/schedules/{id}/toggle   # Enable/Disable schedule
```

### 5.9 Analytics API

```
GET    /api/v1/analytics/overview      # Dashboard stats
GET    /api/v1/analytics/projects      # Project analytics
GET    /api/v1/analytics/publishing    # Publishing analytics
GET    /api/v1/analytics/performance   # System performance
```

### 5.10 System API

```
GET    /api/v1/health                  # Health check
GET    /api/v1/health/plugins          # Plugins status
GET    /api/v1/logs                    # System logs
GET    /api/v1/plugins                 # List plugins
PUT    /api/v1/plugins/{id}/toggle     # Enable/Disable plugin
```

### 5.11 WebSocket Endpoints

```
WS  /ws/render/{job_id}                # Real-time render progress
WS  /ws/publish/{job_id}               # Real-time publish progress
WS  /ws/notifications                  # System notifications
```

---

## 6. تصميم Core Engine

### 6.1 Domain Models

#### Project Aggregate Root
```python
# core/domain/project/project.py

class Project(BaseEntity):
    title: str
    description: Optional[str]
    script: Optional[str]
    tags: list[str]
    status: ProjectStatus
    template_id: Optional[UUID]
    logo_asset_id: Optional[UUID]
    brand_colors: BrandColors
    settings: ProjectSettings
    
    # Aggregate root controls its invariants
    def start_production(self) -> DomainEvent:
        if self.status not in (ProjectStatus.DRAFT, ProjectStatus.FAILED):
            raise ProductionAlreadyStartedError(self.id)
        self.status = ProjectStatus.IN_PRODUCTION
        return ProductionStarted(project_id=self.id)
    
    def mark_rendered(self, render_job_id: UUID) -> DomainEvent:
        self.status = ProjectStatus.RENDERED
        return ProjectRendered(project_id=self.id, render_job_id=render_job_id)
    
    def apply_template(self, template: Template) -> None:
        self.template_id = template.id
        self.settings = self.settings.merge_with(template.settings)
```

#### OutputProfile Value Object
```python
class OutputProfile:
    """Defines target output specifications"""
    platform: str           # youtube|tiktok|instagram|...
    variant: str            # main|shorts|reel|feed
    resolution: Resolution  # 1920x1080
    aspect_ratio: AspectRatio  # 16:9|9:16|1:1|4:5
    fps: int
    format: VideoFormat     # mp4|mov|webm
    max_duration: Optional[float]
    max_file_size: Optional[int]
```

### 6.2 Production Pipeline

```python
# core/pipeline/production_pipeline.py

class ProductionPipeline:
    """
    Orchestrates the full production process.
    Depends only on Port abstractions, not concrete implementations.
    """
    
    def __init__(
        self,
        voice_provider: VoicePort,
        renderer: RendererPort,
        exporter: ExporterPort,
        event_bus: EventBusPort,
        # ... other ports
    ):
        self._stages: list[PipelineStage] = [
            ScriptProcessorStage(),
            SceneDetectorStage(),
            TimelineGeneratorStage(),
            VoiceGeneratorStage(voice_provider),
            SubtitleGeneratorStage(),
            AssetAssignerStage(),
            LayerCompositorStage(),
            EffectsApplierStage(),
            TransitionsApplierStage(),
            RendererStage(renderer),
            EncoderStage(),
            ThumbnailGeneratorStage(),
            ExporterStage(exporter),
        ]
    
    async def run(
        self,
        context: PipelineContext,
        progress_callback: Callable[[float, str], None]
    ) -> PipelineResult:
        for i, stage in enumerate(self._stages):
            try:
                context = await stage.execute(context)
                progress = (i + 1) / len(self._stages) * 100
                await progress_callback(progress, stage.name)
            except PipelineStageError as e:
                return PipelineResult.failure(stage.name, e)
        return PipelineResult.success(context.output_paths)
```

#### PipelineContext
```python
class PipelineContext:
    """Immutable context passed through stages"""
    project: Project
    timeline: Timeline
    settings: RenderSettings
    temp_dir: Path
    assets: dict[UUID, Asset]
    voice_clips: dict[UUID, Path]   # scene_id -> audio path
    subtitle_data: list[SubtitleEntry]
    render_result: Optional[RenderResult]
    output_paths: dict[str, Path]   # format -> path
```

---

## 7. تصميم Timeline Engine

### 7.1 بنية Timeline

```
Timeline
├── fps: int (24|30|60)
├── resolution: Resolution
├── duration: float (seconds)
│
├── Tracks (ordered list)
│   ├── VideoTrack
│   │   └── Scenes
│   │       └── Layers
│   │           └── VideoLayer | ImageLayer | TextLayer | LogoLayer
│   │
│   ├── AudioTrack
│   │   └── Scenes → AudioLayer
│   │
│   ├── MusicTrack
│   │   └── Scenes → MusicLayer
│   │
│   ├── SubtitleTrack
│   │   └── Scenes → SubtitleLayer
│   │
│   ├── AnimationTrack
│   │   └── Scenes → AnimationLayer
│   │
│   └── OverlayTrack
│       └── Scenes → OverlayLayer
│
└── Markers (list of {time, label, color})
```

### 7.2 Layer Types

```python
# core/domain/timeline/layer.py

class Layer(BaseEntity):
    """Base layer"""
    scene_id: UUID
    type: LayerType
    position: int
    start_time: float
    end_time: Optional[float]
    asset_id: Optional[UUID]
    properties: LayerProperties
    effects: list[EffectConfig]
    animations: list[KeyframeAnimation]
    is_visible: bool
    z_index: int

class VideoLayer(Layer):
    properties: VideoLayerProperties
    # volume, playback_rate, crop, fit_mode

class ImageLayer(Layer):
    properties: ImageLayerProperties
    # position_x, position_y, width, height, opacity, fit_mode

class TextLayer(Layer):
    properties: TextLayerProperties
    # content, font_family, font_size, color, alignment, position

class SubtitleLayer(Layer):
    properties: SubtitleLayerProperties
    # format (srt|ass|burned), style config

class LogoLayer(ImageLayer):
    properties: LogoLayerProperties
    # corner, margin, opacity
```

### 7.3 Timeline Builder

```python
class TimelineBuilder:
    """
    Builds Timeline from a Project automatically.
    Called by TimelineGeneratorStage in the pipeline.
    """
    
    def build_from_project(self, project: Project, scenes: list[SceneData]) -> Timeline:
        timeline = Timeline(project_id=project.id, fps=30)
        
        video_track = timeline.add_track(TrackType.VIDEO)
        audio_track = timeline.add_track(TrackType.AUDIO)
        subtitle_track = timeline.add_track(TrackType.SUBTITLE)
        music_track = timeline.add_track(TrackType.MUSIC)
        
        current_time = 0.0
        for scene_data in scenes:
            scene = video_track.add_scene(
                start=current_time,
                end=current_time + scene_data.duration
            )
            # Add layers based on scene content and template
            self._apply_template_to_scene(scene, project.template, scene_data)
            current_time += scene_data.duration
        
        timeline.duration = current_time
        return timeline
```

---

## 8. تصميم Rendering Engine

### 8.1 مبدأ العزل

```
Core Pipeline
     │
     ▼
RendererPort (abstract interface in shared/ports)
     │
     ├── FFmpegRendererPlugin (default)
     └── CustomRendererPlugin (future)
```

### 8.2 RendererPort (العقد)

```python
# shared/ports/renderer_port.py

class RendererPort(ABC):
    """
    Abstract contract for the rendering engine.
    Core only depends on this. Never on FFmpeg directly.
    """
    
    @abstractmethod
    async def render(
        self,
        timeline: Timeline,
        assets: dict[UUID, ResolvedAsset],
        settings: RenderSettings,
        progress_callback: Callable[[float], Awaitable[None]]
    ) -> RenderResult:
        ...
    
    @abstractmethod
    async def generate_thumbnail(
        self,
        render_result: RenderResult,
        config: ThumbnailConfig
    ) -> Path:
        ...
    
    @abstractmethod
    def get_capabilities(self) -> RendererCapabilities:
        ...
```

### 8.3 FFmpegRendererPlugin

```python
# plugins/renderer/ffmpeg_renderer.py

class FFmpegRendererPlugin(RendererPort):
    """
    FFmpeg-based renderer. The ONLY place in the system where
    FFmpeg is used for rendering. All other code uses RendererPort.
    """
    
    async def render(self, timeline, assets, settings, progress_callback):
        # 1. Build FFmpeg filter graph from Timeline
        filter_graph = self._build_filter_graph(timeline, assets)
        
        # 2. Compose FFmpeg command
        cmd = self._build_ffmpeg_command(filter_graph, settings)
        
        # 3. Execute with progress monitoring
        result = await self._execute_with_progress(cmd, timeline.duration, progress_callback)
        
        return RenderResult(output_path=result.path, duration=timeline.duration)
    
    def _build_filter_graph(self, timeline: Timeline, assets) -> FilterGraph:
        """Convert Timeline model to FFmpeg filtergraph"""
        builder = FFmpegFilterGraphBuilder()
        
        for track in timeline.tracks:
            for scene in track.scenes:
                for layer in sorted(scene.layers, key=lambda l: l.z_index):
                    builder.add_layer(layer, assets.get(layer.asset_id))
        
        return builder.build()
```

### 8.4 ThumbnailEngine

```python
# core/pipeline/stages/thumbnail_generator.py

class ThumbnailGeneratorStage(PipelineStage):
    """
    Generates thumbnail using Pillow + template system.
    Independent from rendering - can be called separately.
    """
    
    async def execute(self, ctx: PipelineContext) -> PipelineContext:
        config = ThumbnailConfig(
            template=ctx.project.template,
            title=ctx.project.title,
            logo_asset=ctx.assets.get(ctx.project.logo_asset_id),
            colors=ctx.project.brand_colors,
        )
        thumbnail_path = await self._renderer.generate_thumbnail(
            ctx.render_result, config
        )
        ctx.output_paths["thumbnail"] = thumbnail_path
        return ctx
```

---

## 9. تصميم Publishing Engine

### 9.1 المبادئ

```
PublishingService (Core)
       │
       ├── لا يحتوي على أي منطق خاص بمنصة
       │
PublisherPort (abstract contract)
       │
       ├── YouTubePublisherPlugin
       ├── TikTokPublisherPlugin (future)
       └── InstagramPublisherPlugin (future)
```

### 9.2 PublisherPort (العقد)

```python
# shared/ports/publisher_port.py

class PublisherPort(ABC):
    
    @abstractmethod
    async def authenticate(self, credentials: dict) -> AuthResult:
        ...
    
    @abstractmethod
    async def validate_content(
        self,
        content: PublishableContent,
        profile: PlatformProfile
    ) -> ValidationResult:
        ...
    
    @abstractmethod
    async def upload(
        self,
        content: PublishableContent,
        account: PublisherAccount,
        metadata: PublishMetadata,
        progress_callback: Callable[[float], Awaitable[None]]
    ) -> UploadResult:
        ...
    
    @abstractmethod
    async def schedule(
        self,
        upload_result: UploadResult,
        scheduled_at: datetime
    ) -> ScheduleResult:
        ...
    
    @abstractmethod
    def get_platform_profile(self) -> PlatformProfile:
        """Returns platform constraints and capabilities"""
        ...
    
    @property
    @abstractmethod
    def platform_name(self) -> str:
        ...
```

### 9.3 PlatformProfile

```python
class PlatformProfile:
    """
    Defines all constraints for a platform.
    Used before exporting to ensure compatibility.
    """
    max_duration: Optional[float]        # seconds
    max_file_size: Optional[int]         # bytes
    supported_formats: list[str]
    supported_resolutions: list[Resolution]
    supported_aspect_ratios: list[AspectRatio]
    thumbnail_required: bool
    thumbnail_size: Optional[Resolution]
    max_title_length: int
    max_description_length: int
    max_tags: int
    supports_scheduling: bool
    supports_chapters: bool
    supports_subtitles: bool
```

### 9.4 Publishing Service

```python
class PublishingService:
    """
    Core publishing orchestration. Platform-agnostic.
    """
    
    def __init__(
        self,
        platform_registry: PlatformRegistry,
        job_repository: PublishingJobRepository,
        event_bus: EventBusPort,
    ):
        ...
    
    async def publish(
        self,
        export_path: Path,
        account: PublisherAccount,
        metadata: PublishMetadata,
        scheduled_at: Optional[datetime] = None,
    ) -> PublishingJob:
        plugin = self._registry.get_publisher(account.platform.name)
        
        # Validate content against platform profile
        profile = plugin.get_platform_profile()
        validation = await plugin.validate_content(content, profile)
        if not validation.is_valid:
            raise ContentValidationError(validation.errors)
        
        # Create job
        job = PublishingJob.create(account_id=account.id, scheduled_at=scheduled_at)
        await self._job_repo.save(job)
        
        if scheduled_at:
            await self._event_bus.publish(PublishScheduled(job_id=job.id, at=scheduled_at))
        else:
            await self._event_bus.publish(PublishQueued(job_id=job.id))
        
        return job
    
    async def execute_job(self, job: PublishingJob) -> None:
        plugin = self._registry.get_publisher(job.account.platform.name)
        try:
            result = await plugin.upload(
                content=job.content,
                account=job.account,
                metadata=job.metadata,
                progress_callback=lambda p: self._emit_progress(job.id, p)
            )
            job.mark_published(result.platform_post_id, result.platform_url)
        except PublishError as e:
            job.mark_failed(str(e))
            if job.can_retry:
                job.schedule_retry()
```

### 9.5 Retry Policy

```python
class RetryPolicy:
    max_retries: int = 3
    backoff_strategy: BackoffStrategy = ExponentialBackoff(base=60)  # seconds
    
    def next_retry_at(self, attempt: int) -> datetime:
        delay = self.backoff_strategy.get_delay(attempt)
        return datetime.utcnow() + timedelta(seconds=delay)
    
    def should_retry(self, error: Exception) -> bool:
        # Network errors: yes. Auth errors: no.
        return isinstance(error, (NetworkError, RateLimitError, TemporaryError))
```

---

## 10. تصميم Plugin System

### 10.1 المبادئ

```
Plugin = Implementation of a Port defined in shared/ports/
Core لا يعلم بوجود أي Plugin محدد
PluginRegistry يربط Port بالـ Plugin عند بدء التطبيق
```

### 10.2 PluginRegistry

```python
# plugins/registry.py

class PluginRegistry:
    """
    Central registry. Loaded at startup from plugin_config.yaml.
    Core services receive implementations via Dependency Injection.
    """
    
    def __init__(self):
        self._plugins: dict[str, Any] = {}
    
    def register(self, plugin_type: str, name: str, plugin: Any) -> None:
        self._plugins[f"{plugin_type}:{name}"] = plugin
    
    def get_voice_provider(self, name: str) -> VoicePort:
        return self._plugins[f"voice:{name}"]
    
    def get_renderer(self) -> RendererPort:
        return self._plugins["renderer:default"]
    
    def get_publisher(self, platform: str) -> PublisherPort:
        return self._plugins[f"publisher:{platform}"]
    
    def get_effect(self, name: str) -> EffectPort:
        return self._plugins[f"effect:{name}"]
    
    def list_publishers(self) -> list[PublisherPort]:
        return [v for k, v in self._plugins.items() if k.startswith("publisher:")]
```

### 10.3 plugin_config.yaml

```yaml
plugins:
  voice:
    default: piper
    enabled:
      - name: piper
        module: plugins.voice.piper_plugin
        class: PiperVoicePlugin
        config:
          model_path: ./models/piper
      - name: coqui
        module: plugins.voice.coqui_plugin
        class: CoquiVoicePlugin
  
  renderer:
    default: ffmpeg
    enabled:
      - name: ffmpeg
        module: plugins.renderer.ffmpeg_renderer
        class: FFmpegRendererPlugin
  
  exporter:
    default: ffmpeg
    enabled:
      - name: ffmpeg
        module: plugins.exporter.ffmpeg_exporter
        class: FFmpegExporterPlugin
  
  publishers:
    enabled:
      - name: youtube
        module: plugins.publishers.youtube.youtube_plugin
        class: YouTubePublisherPlugin
  
  effects:
    enabled:
      - name: fade
        module: plugins.effects.fade_effect
        class: FadeEffect
      - name: zoom
        module: plugins.effects.zoom_effect
        class: ZoomEffect
      - name: ken_burns
        module: plugins.effects.ken_burns_effect
        class: KenBurnsEffect
  
  transitions:
    enabled:
      - name: fade
        module: plugins.transitions.fade_transition
        class: FadeTransition
      - name: crossfade
        module: plugins.transitions.crossfade_transition
        class: CrossFadeTransition
  
  subtitle:
    enabled:
      - name: srt
        module: plugins.subtitle.srt_subtitle
        class: SRTSubtitle
      - name: ass
        module: plugins.subtitle.ass_subtitle
        class: ASSSubtitle
      - name: burned
        module: plugins.subtitle.burned_subtitle
        class: BurnedSubtitle
```

### 10.4 Plugin Loader

```python
class PluginLoader:
    """Loads plugins from config at startup"""
    
    def load_all(self, config: dict, registry: PluginRegistry) -> None:
        for plugin_type, type_config in config["plugins"].items():
            for plugin_def in type_config.get("enabled", []):
                plugin_instance = self._instantiate(plugin_def)
                registry.register(plugin_type, plugin_def["name"], plugin_instance)
    
    def _instantiate(self, plugin_def: dict) -> Any:
        module = importlib.import_module(plugin_def["module"])
        cls = getattr(module, plugin_def["class"])
        return cls(config=plugin_def.get("config", {}))
```

---

## 11. تصميم واجهة FastAPI

### 11.1 الصفحات الرئيسية

| الصفحة | URL | الوصف |
|--------|-----|-------|
| Dashboard | `/` | إحصاءات ونظرة عامة |
| Projects | `/projects` | قائمة المشاريع |
| Project Detail | `/projects/{id}` | تفاصيل المشروع |
| Timeline Editor | `/projects/{id}/timeline` | محرر Timeline تفاعلي |
| Media Library | `/assets` | مكتبة الأصول |
| Templates | `/templates` | إدارة القوالب |
| Voices | `/voices` | محركات الصوت |
| Render Queue | `/render-queue` | قائمة انتظار الرندر |
| Publishing Queue | `/publishing-queue` | قائمة انتظار النشر |
| Platforms | `/platforms` | المنصات المتصلة |
| Schedules | `/schedules` | الجدول الزمني للنشر |
| Logs | `/logs` | سجل العمليات |
| Analytics | `/analytics` | التحليلات |
| Settings | `/settings` | الإعدادات |
| System Health | `/health` | حالة النظام |

### 11.2 HTMX Patterns

```html
<!-- Real-time render progress via polling -->
<div id="render-progress"
     hx-get="/api/v1/production/jobs/{{ job_id }}/progress"
     hx-trigger="every 2s"
     hx-swap="innerHTML">
    <div class="progress-bar" style="width: {{ progress }}%"></div>
    <span>{{ stage_name }}</span>
</div>

<!-- Instant asset search -->
<input type="text"
       name="q"
       hx-get="/assets/search"
       hx-trigger="keyup changed delay:300ms"
       hx-target="#asset-grid">

<!-- Project card actions -->
<button hx-post="/projects/{{ id }}/render"
        hx-confirm="Start rendering?"
        hx-swap="outerHTML"
        hx-target="#project-{{ id }}-status">
    Render
</button>
```

### 11.3 WebSocket Integration

```javascript
// static/js/app.js

class RenderProgressMonitor {
    constructor(jobId) {
        this.ws = new WebSocket(`/ws/render/${jobId}`);
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.updateProgress(data.progress, data.stage, data.message);
        };
    }
    
    updateProgress(progress, stage, message) {
        document.getElementById('progress-bar').style.width = `${progress}%`;
        document.getElementById('stage-name').textContent = stage;
        document.getElementById('progress-message').textContent = message;
    }
}
```

### 11.4 Dependency Injection Setup

```python
# interfaces/web/dependencies.py

def get_plugin_registry(request: Request) -> PluginRegistry:
    return request.app.state.plugin_registry

def get_project_service(
    session: AsyncSession = Depends(get_db_session),
    registry: PluginRegistry = Depends(get_plugin_registry),
) -> ProjectService:
    repo = SQLProjectRepository(session)
    event_bus = InMemoryEventBus()
    return ProjectService(repo, event_bus)

def get_production_service(
    session: AsyncSession = Depends(get_db_session),
    registry: PluginRegistry = Depends(get_plugin_registry),
) -> ProductionService:
    renderer = registry.get_renderer()
    return ProductionService(
        pipeline=ProductionPipeline(renderer=renderer, ...),
        job_repo=SQLRenderJobRepository(session),
    )
```

---

## 12. تصميم نظام المهام المجدولة

### 12.1 APScheduler Setup

```python
# scheduler/scheduler.py

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

class PlatformScheduler:
    def __init__(self, settings: Settings):
        self._scheduler = AsyncIOScheduler(
            jobstores={
                "default": SQLAlchemyJobStore(url=settings.DATABASE_URL)
            },
            job_defaults={
                "coalesce": True,
                "max_instances": 3,
                "misfire_grace_time": 60
            }
        )
    
    def start(self):
        # System maintenance jobs
        self._scheduler.add_job(
            cleanup_old_logs, "cron", hour=2, id="cleanup_logs"
        )
        self._scheduler.add_job(
            check_platform_health, "interval", minutes=30, id="platform_health"
        )
        self._scheduler.start()
    
    def schedule_publish(self, job_id: UUID, at: datetime):
        self._scheduler.add_job(
            execute_publish_job,
            trigger="date",
            run_date=at,
            args=[str(job_id)],
            id=f"publish_{job_id}",
        )
    
    def schedule_retry(self, job_id: UUID, at: datetime):
        self._scheduler.add_job(
            execute_publish_job,
            trigger="date",
            run_date=at,
            args=[str(job_id)],
            id=f"retry_{job_id}",
            replace_existing=True
        )
```

### 12.2 Job Types

| Job | Trigger | الوصف |
|-----|---------|-------|
| `execute_publish_job` | date / interval | تنفيذ مهمة نشر |
| `retry_failed_job` | date (backoff) | إعادة محاولة النشر الفاشل |
| `check_platform_health` | interval (30min) | التحقق من اتصال المنصات |
| `cleanup_old_logs` | cron (daily 2am) | حذف السجلات القديمة |
| `cleanup_temp_files` | cron (daily 3am) | حذف الملفات المؤقتة |
| `recurring_publish` | cron (user-defined) | النشر المتكرر |

---

## 13. خطة التنفيذ

### المرحلة 1 - MVP Core (الأسابيع 1-4)

**الهدف:** نظام يتيح إنشاء مشروع، توليد فيديو، ونشره على YouTube.

#### الأسبوع 1: الأساس
- [ ] هيكل المشروع الكامل
- [ ] Shared Kernel (BaseEntity, ValueObjects, Ports)
- [ ] Database Models + Alembic migrations
- [ ] SQLAlchemy session setup
- [ ] Settings (Pydantic BaseSettings)
- [ ] Plugin Registry + Loader
- [ ] FastAPI app structure + health endpoint

#### الأسبوع 2: Core Domain + Pipeline
- [ ] Project domain model
- [ ] Timeline domain model (Timeline, Track, Scene, Layer)
- [ ] Asset domain model
- [ ] PipelineContext
- [ ] ScriptProcessorStage + SceneDetectorStage
- [ ] TimelineGeneratorStage + TimelineBuilder
- [ ] FFmpegRendererPlugin (basic render)
- [ ] FFmpegExporterPlugin (MP4 only)
- [ ] ThumbnailGeneratorStage (Pillow)

#### الأسبوع 3: Voice + Subtitle + Production API
- [ ] PiperVoicePlugin
- [ ] SRT SubtitlePlugin
- [ ] BurnedSubtitlePlugin
- [ ] Full ProductionPipeline
- [ ] RenderJob management
- [ ] REST API: Projects, Production
- [ ] WebSocket: render progress

#### الأسبوع 4: Publishing + Dashboard
- [ ] YouTubePublisherPlugin (OAuth2 + upload)
- [ ] PublishingService + RetryPolicy
- [ ] APScheduler setup
- [ ] REST API: Publishing, Platforms, Schedules
- [ ] FastAPI/Jinja2 Dashboard (basic)
- [ ] HTMX interactions
- [ ] SQLite → working end-to-end demo

### المرحلة 2 - Enhanced MVP (الأسابيع 5-8)

- [ ] Effects Engine (Fade, Zoom, Pan, Ken Burns)
- [ ] Transitions Engine (Fade, CrossFade, Slide)
- [ ] Template Engine (2-3 built-in templates)
- [ ] Assets Library (full upload/search/categorize)
- [ ] Multi-output profiles (16:9, 9:16, 1:1)
- [ ] CoquiVoicePlugin + KokoroVoicePlugin
- [ ] ASS Subtitle support
- [ ] Analytics dashboard
- [ ] Full web UI polish
- [ ] pytest test suite (unit + integration)

### المرحلة 3 - Scale Ready (الأسابيع 9-12)

- [ ] PostgreSQL migration (swap SQLite → PG)
- [ ] Background worker queue (Celery/ARQ)
- [ ] TikTok Publisher Plugin
- [ ] Instagram Publisher Plugin
- [ ] Multi-tenant foundation (user model, isolation)
- [ ] S3 Storage Plugin
- [ ] Performance profiling + optimization
- [ ] Docker Compose setup
- [ ] API authentication (JWT)

### المرحلة 4 - SaaS Ready

- [ ] Full multi-tenancy
- [ ] Subscription/billing hooks
- [ ] Facebook, LinkedIn, X Publisher Plugins
- [ ] Advanced Template Builder
- [ ] Animation Engine (Keyframes)
- [ ] Cloud Rendering Option

---

## 14. الأداء والمعالجة المتوازية

### 14.1 Async Architecture

```python
# كل العمليات الـ I/O-bound تستخدم async/await
async def render_project(project_id: UUID) -> RenderResult:
    async with asyncio.TaskGroup() as tg:
        voice_task = tg.create_task(generate_voice(scenes))
        assets_task = tg.create_task(resolve_assets(timeline))
    
    voices, assets = voice_task.result(), assets_task.result()
    return await renderer.render(timeline, assets, voices)
```

### 14.2 CPU-Bound Work (FFmpeg)

```python
# استخدام ProcessPoolExecutor للعمليات الثقيلة
async def execute_ffmpeg(cmd: list[str]) -> Path:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        ProcessPoolExecutor(max_workers=4),
        _run_ffmpeg_sync, cmd
    )
```

### 14.3 Parallel Export

```python
# تصدير نسب أبعاد متعددة بشكل متوازٍ
async def export_all_profiles(
    render_result: RenderResult,
    profiles: list[OutputProfile]
) -> dict[str, Path]:
    tasks = [
        exporter.export(render_result, profile)
        for profile in profiles
    ]
    results = await asyncio.gather(*tasks)
    return {p.variant: r for p, r in zip(profiles, results)}
```

### 14.4 Streaming Large Files

```python
# Streaming upload for large videos
@router.get("/assets/{id}/stream")
async def stream_asset(id: UUID):
    path = await asset_service.get_path(id)
    return FileResponse(path, media_type="video/mp4")
```

### 14.5 Database Optimization

```sql
-- فهارس ضرورية للأداء
CREATE INDEX idx_projects_status ON projects(status);
CREATE INDEX idx_render_jobs_status ON render_jobs(status);
CREATE INDEX idx_publishing_jobs_status ON publishing_jobs(status);
CREATE INDEX idx_publishing_jobs_scheduled ON publishing_jobs(scheduled_at) 
    WHERE status = 'scheduled';
CREATE INDEX idx_scenes_timeline ON scenes(timeline_id, start_time);
CREATE INDEX idx_layers_scene ON layers(scene_id, z_index);
```

### 14.6 Caching Strategy

```python
# Cache template resolution (rarely changes)
@cached(ttl=300, key="template:{template_id}")
async def get_template(template_id: UUID) -> Template:
    ...

# Cache platform profiles (static data)
@cached(ttl=3600, key="platform_profile:{platform}")
def get_platform_profile(platform: str) -> PlatformProfile:
    ...
```

---

## 15. إضافة منصات جديدة

### 15.1 الخطوات الوحيدة المطلوبة

**لإضافة TikTok (مثلاً) لا تحتاج لتعديل أي ملف في core/ أو publishing/domain/:**

#### الخطوة 1: إنشاء Plugin
```python
# plugins/publishers/tiktok/tiktok_plugin.py

class TikTokPublisherPlugin(PublisherPort):
    
    @property
    def platform_name(self) -> str:
        return "tiktok"
    
    def get_platform_profile(self) -> PlatformProfile:
        return PlatformProfile(
            max_duration=600,          # 10 minutes
            max_file_size=4 * 1024**3, # 4GB
            supported_formats=["mp4"],
            supported_aspect_ratios=[AspectRatio.VERTICAL_9_16],
            max_title_length=150,
            supports_scheduling=True,
        )
    
    async def authenticate(self, credentials: dict) -> AuthResult:
        # TikTok OAuth2 implementation
        ...
    
    async def upload(self, content, account, metadata, progress_callback) -> UploadResult:
        # TikTok Upload API implementation
        ...
```

#### الخطوة 2: تسجيل في plugin_config.yaml فقط
```yaml
publishers:
  enabled:
    - name: youtube
      module: plugins.publishers.youtube.youtube_plugin
      class: YouTubePublisherPlugin
    # إضافة هذا السطر فقط:
    - name: tiktok
      module: plugins.publishers.tiktok.tiktok_plugin
      class: TikTokPublisherPlugin
```

#### الخطوة 3: إضافة Platform إلى قاعدة البيانات
```sql
INSERT INTO publishing_platforms (name, display_name, plugin, constraints)
VALUES (
    'tiktok',
    'TikTok',
    'tiktok',
    '{"max_duration": 600, "supported_aspect_ratios": ["9:16"]}'
);
```

**هذا كل شيء.** النظام يكتشف Plugin الجديد تلقائياً ويظهر في واجهة المستخدم عبر `platform_registry.list_publishers()`.

### 15.2 ضمانات Open/Closed Principle

```
✓ Core لا يتغير                    (Open/Closed)
✓ Publishing Engine لا يتغير       (Open/Closed)
✓ Interfaces لا تتغير              (Open/Closed)
✓ Database Schema لا يتغير        (Publishing_platforms يستوعب أي منصة)
✓ فقط ملف جديد + سطر في config    (فقط الإضافة)
```

---

## ملاحظات ختامية

### مبادئ لا تُنتهك
1. **Core يعتمد فقط على Shared Kernel** — لا import من infrastructure أو plugins
2. **FFmpeg في Renderer Plugin فقط** — لا استدعاء ffmpeg مباشر في أي مكان آخر
3. **كل منصة نشر هي Plugin** — لا منطق منصة في Core أو PublishingService
4. **Repository Interfaces في Core** — Implementations في Infrastructure
5. **Use Cases في Application** — لا business logic في Interfaces أو Routes

### جاهزية لـ SaaS
- كل entity يحتوي على `owner_id` (UUID) يمكن إضافته لاحقاً بـ Alembic migration واحد
- Row-Level Security في PostgreSQL يمنع عزل البيانات بين المستأجرين
- Plugin System يسمح بتخصيص Features لكل مستأجر

---

*نهاية الوثيقة — الإصدار 1.0.0*

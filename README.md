# InfraNex AI — Backend Service (`infranex-backend`)

Civic Infrastructure Reporting & AI-Assisted Repair Verification REST API.

---

## 1. Project Overview

InfraNex AI is an intelligent civic reporting platform that enables citizens to submit photographic evidence of public infrastructure defects (such as potholes, streetlight failures, garbage pileups, and damaged roadways), tracks them through a multi-stage municipal repair lifecycle, and verifies remediations before closing tickets.

This repository contains the standalone **FastAPI backend service**, providing:
- Asynchronous civic intake with cryptographic reference ID generation (`INF-YYYYMMDD-XXXX`).
- Multi-domain municipal routing (Roads, Electricity, Sanitation, Streetlights, General Maintenance).
- Role-based access control (RBAC) across `CITIZEN`, `REVIEWER`, `AUTHORITY`, and `ADMIN` boundaries.
- Photographic evidence attachment and audit timeline logging.
- AI defect assessment interfaces (offline CLIP engine / external inference API).
- Repair verification with before/after comparative analysis.
- Public defect discovery with geographic proximity filtering.

---

## 2. Architecture & Directory Structure

```text
infranex-backend/
├── alembic/                          # Alembic database migrations (versions a4029 - g2678)
│   ├── env.py                        # Migration environment script
│   └── versions/                     # Revision scripts
├── api/
│   └── index.py                      # Vercel serverless ASGI handler
├── app/
│   ├── api/                          # FastAPI routers
│   │   ├── admin.py                  # Administrative user management & audit logs
│   │   ├── assessments.py            # AI incident assessments
│   │   ├── auth.py                   # JWT authentication & session verification
│   │   ├── authority.py              # Work order dispatches & contractor actions
│   │   ├── complaints.py             # Complaint CRUD, status transitions, evidence
│   │   ├── disputes.py               # Citizen dispute filing & resolution
│   │   ├── health.py                 # System health and database connectivity
│   │   ├── notifications.py          # User notification preferences & alerts
│   │   ├── public.py                 # Public discovery & sanitized complaint feed
│   │   ├── reviewer.py               # Human reviewer audit queue & decisions
│   │   └── verifications.py          # AI repair verifications
│   ├── core/
│   │   ├── config.py                 # Pydantic/dataclass application settings
│   │   ├── database.py               # SQLAlchemy engine, session maker, NullPool
│   │   ├── security.py               # JWT decode/validation & role dependency guards
│   │   └── security_crypto.py        # PBKDF2 password hashing & HMAC verification
│   ├── models/                       # SQLAlchemy declarative models
│   ├── repositories/                 # Data access repository layer
│   ├── schemas/                      # Pydantic request & response schemas
│   ├── services/                     # Business logic & domain services
│   ├── static/                       # Web portal preview files
│   └── storage/                      # File storage abstraction layer
├── scripts/                          # Utility & CLI tools (terminal reviewer)
├── tests/                            # Pytest test suite (119 automated tests)
├── .env.example                      # Sanitized environment configuration template
├── .gitignore                        # Git ignore rules for data, models, & credentials
├── .vercelignore                     # Serverless function packaging exclusions
├── alembic.ini                       # Alembic CLI configuration
├── requirements.txt                  # Python dependencies
├── vercel.json                       # Vercel routing configuration
└── README.md                         # This documentation
```

---

## 3. Runtime Requirements

- **Python**: `3.11` or `3.12` recommended.
- **Database (Local)**: SQLite (standard library).
- **Database (Production Target)**: PostgreSQL 15+ (with serverless connection pooler / PgBouncer).
- **Key Dependencies**:
  - `fastapi>=0.110.0`
  - `uvicorn[standard]>=0.28.0`
  - `sqlalchemy>=2.0.28`
  - `alembic>=1.13.1`
  - `pydantic>=2.6.0`
  - `pyjwt>=2.8.0`
  - `psycopg2-binary>=2.9.9`
  - `Pillow>=10.0.0`
  - `pytest>=8.0.0`

---

## 4. Safe Local Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/<user>/infranex-backend.git
   cd infranex-backend
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv .venv
   # Windows PowerShell:
   .venv\Scripts\Activate.ps1
   # Linux / macOS:
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**:
   ```bash
   cp .env.example .env
   ```
   *(Local defaults in `.env.example` point to local SQLite and mock AI provider without requiring external API keys).*

---

## 5. Starting the Local Server

Run the development server with live reload:
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- **Interactive API Documentation (Swagger UI)**: `http://localhost:8000/docs`
- **Alternative Documentation (ReDoc)**: `http://localhost:8000/redoc`
- **Web Portal Preview**: `http://localhost:8000/portal`

---

## 6. Running the Test Suite

The test suite runs against an in-memory SQLite database (`:memory:`) with mocked AI providers and does not mutate local files:
```bash
pytest tests/ -v
```
Expected output: **119 passed**.

---

## 7. Database Migrations (Alembic)

Database schema versions are managed with Alembic.

- **Check current migration state**:
  ```bash
  alembic current
  ```
- **Apply migrations**:
  ```bash
  alembic upgrade head
  ```
- **Roll back last migration**:
  ```bash
  alembic downgrade -1
  ```

---

## 8. Health Check Endpoint

Verified from `app/api/health.py`:
- **Endpoint**: `GET /health`
- **Response**:
  ```json
  {
    "status": "healthy",
    "app_name": "InfraNex AI Backend",
    "version": "0.1.0",
    "database": "connected",
    "environment": "development"
  }
  ```

---

## 9. Environment Variable Reference

| Variable | Default (Local) | Production Requirement | Description |
| :--- | :--- | :--- | :--- |
| `ENVIRONMENT` | `development` | `production` | Enables production security controls; disables dev auth headers. |
| `DEBUG` | `True` | `False` | Disables debug stack traces in HTTP responses. |
| `DATABASE_URL` | `sqlite:///./infranex_dev.db` | `postgresql://...` | Connection URI with SSL and connection pooling. |
| `JWT_SECRET_KEY` | `infranex-cryptographic-...` | Mandatory custom secret | Cryptographic HMAC secret for signing access tokens. |
| `UPLOAD_DIR` | `./uploads` | N/A (Cloud Storage) | Local directory for uploaded photos. |
| `MAX_UPLOAD_SIZE_BYTES` | `10485760` (10MB) | `4718592` (4.5MB on Vercel) | Maximum allowed file upload size. |
| `AI_PROVIDER` | `clip` | `external` or `gemini` | Defect detection provider. |
| `CORS_ORIGINS` | `http://localhost:8000,...` | Frontend domains | Comma-separated allowed origins for browser/client requests. |

---

## 10. Security Warnings & Access Control Notice

> [!WARNING]
> **Default Development Accounts & Simulation Headers:**
> - When `ENVIRONMENT == "development"`, endpoints permit simulation headers (`X-Role`, `X-User-ID`, `X-Department`) and static tokens (`DEV_REVIEWER_TOKEN`, `DEV_AUTHORITY_TOKEN`) for rapid local testing.
> - Default seed accounts (`admin`, `reviewer_lead`, `bbmp_roads`, etc.) are seeded automatically in local development.
> - **In production**: Set `ENVIRONMENT=production` to strictly require valid cryptographic JWT Bearer tokens and enforce RBAC policies.

---

## 11. Current Limitations & Planned Architecture

| Component | Current Local Implementation | Planned Production Target | Status / Blocker |
| :--- | :--- | :--- | :--- |
| **Database** | SQLite file on disk | Managed PostgreSQL (Neon / Supabase) | ENUM reconciliation migration required before deploying to Postgres. |
| **File Storage** | Local directory (`uploads/`) | S3-compatible Object Storage (R2 / S3) | Vercel filesystem is read-only; pre-signed S3 upload URLs required. |
| **AI Assessment** | Offline CLIP model (605MB weights) | Decoupled inference API (Cloud Run / Gemini) | CLIP model weights exceed Vercel 250MB bundle limit and are excluded from Git. |
| **Hosting** | Local machine (`uvicorn`) | Vercel Serverless Function | Entrypoint (`api/index.py`) and `vercel.json` are prepared for Phase 2. |

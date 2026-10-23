# iClinic - AI Voice & Appointment Platform

An enterprise backend system for automated patient appointment scheduling, voice telephony workflows, and conversational AI booking.

---

## 🛠️ Technology Stack

* **Language**: Python 3.11+
* **Package Manager**: [uv](https://github.com/astral-sh/uv)
* **Web Framework**: [FastAPI](https://fastapi.tiangolo.com/)
* **ASGI Server**: [Uvicorn](https://www.uvicorn.org/)
* **ORM**: [SQLAlchemy 2.0 (Async)](https://docs.sqlalchemy.org/)
* **Database Driver**: [asyncpg](https://magicstack.github.io/asyncpg/)
* **Database**: PostgreSQL
* **Migrations**: [Alembic](https://alembic.sqlalchemy.org/)
* **Configuration**: [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

---

## 📁 Project Structure

```text
src/
├── main.py                          # Service application entrypoint
├── api/
│   ├── rest/                        # FastAPI REST API
│   │   ├── app.py                   # FastAPI application instance (CORS, error handling, metrics)
│   │   ├── dependencies.py          # Route dependencies (e.g., DBSessionDep)
│   │   └── routes/
│   │       ├── voice.py             # Outbound calls & Twilio voice webhooks
│   │       ├── voice_assistant.py   # Browser voice assistant (STT / TTS)
│   │       └── dashboard.py         # Patient chat & dashboard endpoints
│   └── middleware/
│       └── correlation.py           # Request / call correlation IDs
├── config/
│   └── settings.py                  # Environment & DB settings via Pydantic
├── constants/
│   └── enums.py                     # PostgreSQL Enum definitions
├── core/
│   ├── exceptions/                  # Domain exceptions (ClinicError, AppointmentServiceError, SlotUnavailableError)
│   ├── services/                    # Business services
│   │   ├── appointment_service.py        # Atomic book / reschedule / cancel
│   │   ├── conversation_turn_service.py  # Shared per-turn runner for chat, voice and calls
│   │   ├── intent_classification_service.py # Gemini intent classification with offline fallback
│   │   ├── medical_safety_service.py     # Emergency detection
│   │   └── notification_service.py       # SMS / email confirmations and front-desk alerts
│   └── scheduler.py                 # Background jobs (outbound retries, call reconciliation, slot-hold cleanup)
├── control/
│   └── agents/                      # AI Voice & Chat Booking Agent
│       ├── graph.py, edges.py       # LangGraph workflow and routing
│       ├── state.py, prompts.py     # Conversation state and prompts
│       ├── nodes/                   # Intent detection, identity, booking, reschedule, cancel, FAQ, handoff
│       └── tools/                   # Slot, booking, identity and clinic-directory tools
├── data/
│   ├── clients/
│   │   └── postgres.py              # Async SQLAlchemy engine & session factory
│   ├── models/postgres/             # SQLAlchemy ORM models (12 tables + mixins)
│   │   ├── base.py                  # AuditMixin (id, created_at, updated_at, created_by, updated_by)
│   │   ├── location.py              # Locations
│   │   ├── provider.py              # Healthcare Providers (Doctors)
│   │   ├── appointment_type.py      # Appointment Types & duration
│   │   ├── slot.py                  # Available / Held Schedule Slots
│   │   ├── patient.py               # Patient identity & contact details
│   │   ├── conversation.py          # Call / Chat conversations & state timelines
│   │   ├── outbound_call_request.py # Queued outbound call jobs
│   │   ├── outbound_call.py         # Outbound telephony call attempts
│   │   ├── appointment.py           # Booked Appointments
│   │   ├── appointment_cancellation.py # Cancellation audit log
│   │   ├── appointment_reschedule.py   # Reschedule audit log
│   │   └── notification.py          # Patient notifications (SMS / Email)
│   ├── repositories/                # Data access layer
│   ├── migrations/                  # Alembic migration environment and versions
│   └── seed.py                      # Clinic, doctor and patient seed data
├── handlers/
│   └── http_clients/                # External providers
│       ├── gemini_service.py        # Google Gemini LLM (retry, backup model)
│       ├── sarvam_service.py        # Speech-to-text, text-to-speech, translation
│       ├── twilio_service.py        # Telephony and SMS (Twilio)
│       └── audio_storage_service.py # Generated audio storage
├── observability/
│   ├── logging/                     # Logging setup (text or JSON via LOG_FORMAT) with request / call IDs
│   ├── context.py                   # Request and call context
│   └── metrics.py                   # Prometheus metrics
├── schemas/                         # Pydantic request schemas (dashboard, calls, voice)
└── utils/                           # Shared helpers (appointment time, branch names, PII redaction)
```

---

## 🗄️ Database Architecture

The data layer is organized around three core operational domains: **Clinic Scheduling**, **Patient & AI Conversations**, and **Bookings, Audits & Notifications**. All primary and foreign keys use **UUID (v4)** generated automatically via PostgreSQL's native `gen_random_uuid()` for distributed security and unpredictable identifiers.

### 1. Clinic & Scheduling
* **Locations**: Manages clinic branch details, physical addresses, and operational status (`UUID`).
* **Providers**: Represents doctors and clinicians associated with specific clinic locations (`UUID`).
* **Appointment Types**: Defines consultation categories (such as routine checkups or specialist visits) along with their default durations (`UUID`).
* **Slots**: Represents provider availability time blocks (`UUID`). Enforces `end_time > start_time`, strict uniqueness per provider and start time, slot lifecycle tracking (`status`: `available`, `reserved`, `booked`), and temporary active-call holds (`reserved_until`).

### 2. Patient Identity & AI Conversations
* **Patients**: Stores patient profiles, phone numbers, optional emails, origin (`source`: `assistant`, `front_desk`), and date of birth used for voice identity verification (`UUID`).
* **Conversations**: Tracks live AI phone calls and chat interactions, preserving dialogue states, message transcripts, collected patient details, and clinical identity verification timestamps (`identity_verified_at`) (`UUID`).

### 3. Bookings, Telephony, Audits & Alerts
* **Outbound Call Requests**: Manages jobs queued by the system to initiate automated outbound phone calls (`UUID`).
* **Outbound Calls**: Records individual telephony dialing attempts, provider Call SIDs, and call status lifecycle events (`UUID`).
* **Appointments**: Represents bookings linking the patient, slot, consultation type, and originating conversation (`UUID`).
* **Appointment Cancellations**: Dedicated audit log recording patient-initiated cancellations, reason, and the phone conversation in which it occurred (`UUID`).
* **Appointment Reschedules**: Dedicated audit log tracking patient-initiated reschedules, linking `old_appointment_id` to `new_appointment_id`, reason, and conversation (`UUID`).
* **Notifications**: Handles delivery of SMS and email confirmation receipts and reminders to patients (`UUID`).

---

### Core Enums

* **`ChannelType`**: `voice`, `outbound_call`, `chat`
* **`SlotStatus`**: `available`, `reserved`, `booked`
* **`PatientSource`**: `assistant`, `front_desk`
* **`AppointmentStatus`**: `booked`, `rescheduled`, `cancelled`, `completed`
* **`ConversationState`**: `started`, `identifying_patient`, `collecting_details`, `suggesting_slots`, `slot_reserved`, `reconfirming`, `booked`, `abandoned`, `failed`, `handed_to_front_desk`, `no_answer`, `busy`, `retry_scheduled`
* **`OutcomeType`**: `booked`, `abandoned`, `failed`, `handed_to_front_desk`, `not_reached`, `wrong_person`
* **`ConfirmationStatusType`**: `pending`, `sent`, `retrying`, `failed`, `flagged`
* **`OutboundCallRequestStatus`**: `waiting`, `processing`, `started`, `completed`, `cancelled`, `expired`, `failed`
* **`CallStatus`**: `dialing`, `no_answer`, `busy`, `answered`, `failed`
* **`NotificationChannel`**: `sms`, `email`
* **`NotificationStatus`**: `pending`, `sent`, `failed`

---

### Model Architecture Principles

* **Universal UUID Primary & Foreign Keys**: All tables use native `UUID(as_uuid=True)` with server-side `gen_random_uuid()` defaults for predictable security and collision prevention.
* **Directional Foreign Keys Only**: Relationships exist only where a foreign key column is defined (e.g. `Appointment` points to `Patient`, `Slot`, `AppointmentType`, and `Conversation`).
* **Zero Circular Imports**: Independent tables (like `Patient`, `Location`, `AppointmentType`) have zero imports of other models.
* **Database-Level Concurrency & Integrity Protection**:
  * **Double Booking Prevention with Slot Re-use**: Enforced via partial unique index `uq_active_appointment_slot` on `appointments.slot_id WHERE status = 'booked'`. Once an appointment is cancelled or rescheduled, its slot is freed immediately for other patients.
  * **Reschedule Self-Reference Guard**: Check constraint `old_appointment_id <> new_appointment_id` and unique `(old_appointment_id, new_appointment_id)` prevent cyclical self-rescheduling.
  * **Webhook Idempotency**: Enforced via `unique=True` on `outbound_calls.provider_call_id` and composite uniqueness on `(call_request_id, attempt_number)`.
  * **Open Request Deduplication**: Partial unique index on `outbound_call_requests.number_to_call WHERE status IN ('waiting', 'processing', 'started')` preventing duplicate outbound calls to the same patient while a call is active.
  * **Patient Identity Fast Lookups**: Composite index on `patients(full_name, date_of_birth)`.
  * **Referential Integrity**: All foreign keys enforce `ON DELETE RESTRICT` to guarantee no accidental deletion of medical or booking records.

---

## 🚀 Getting Started

### 1. Database & Environment Setup

#### Option A: Running PostgreSQL via Docker Compose (Recommended)
Start an isolated PostgreSQL 16 container with persistent storage:
```bash
docker compose up -d
```

#### Option B: Using a Local PostgreSQL Installation
Ensure your PostgreSQL instance is running on port 5432.

Configure your connection settings in `.env`:
```env
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/iclinic
DB_ECHO=False
```

### 2. Install Dependencies

Install dependencies into your local virtual environment using `uv`:
```bash
uv sync
```

### 3. Run Database Migrations

Generate or apply migrations using Alembic:
```bash
# Generate a new migration revision
uv run alembic revision --autogenerate -m "initial_schema"

# Apply migrations
uv run alembic upgrade head
```

### 4. Seed Clinic Data (Optional)

Populate initial clinic branches, doctors, appointment types, test patients, and schedule slots:
```bash
# Preview the data without modifying the database (dry-run)
uv run python -m src.data.seed --preview

# Insert new records and update existing patients/providers (Upsert)
uv run python -m src.data.seed

# Wipe old test seed data cleanly and re-populate from scratch
uv run python -m src.data.seed --reset
```

### 5. Run the Development Server

```bash
uv run uvicorn src.main:app --reload
```
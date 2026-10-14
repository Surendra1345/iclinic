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
│   │   ├── app.py                   # FastAPI application instance
│   │   ├── dependencies.py          # Route dependencies (e.g., DBSessionDep)
│   │   └── routes/                  # API endpoints (calls, bookings, webhooks, media_ws)
│   └── middleware/                  # CORS, logging, error handling
├── config/
│   └── settings.py                  # Environment & DB settings via Pydantic
├── constants/
│   └── enums.py                     # PostgreSQL Enum definitions
├── core/
│   ├── exceptions/                  # Domain exceptions (SlotTaken, IdentityFailed, etc.)
│   └── services/                    # Business services (identity, slot, booking, call)
├── control/
│   └── agents/                      # AI Voice Booking Agent & tool definitions
├── data/
│   ├── clients/
│   │   └── postgres.py              # Async SQLAlchemy engine & session factory
│   ├── models/postgres/             # SQLAlchemy ORM models (10 tables + mixins)
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
│   │   └── notification.py          # Patient notifications (SMS / Email)
│   ├── repositories/                # Data access layer
│   └── migrations/                  # Alembic migration environment and versions
├── handlers/
│   └── http_clients/                # Telephony (Twilio), STT, TTS, LLM (OpenAI), SMS
├── observability/
│   └── logging/                     # Structured JSON logging
├── schemas/                         # Pydantic request / response schemas
└── utils/                           # Shared utilities
```

---

## 🗄️ Database Architecture

The data layer is organized around three core operational domains: **Clinic Scheduling**, **Patient & AI Conversations**, and **Telephony & Bookings**.

### 1. Clinic & Scheduling
* **Locations**: Manages clinic branch details, physical addresses, and operational status.
* **Providers**: Represents doctors and clinicians associated with specific clinic locations.
* **Appointment Types**: Defines consultation categories (such as routine checkups or specialist visits) along with their default durations.
* **Slots**: Represents provider availability time blocks that patients can reserve.

### 2. Patient Identity & AI Conversations
* **Patients**: Stores patient profiles, phone numbers, emails, and date of birth used for identity verification.
* **Conversations**: Tracks live AI phone calls and chat interactions, preserving dialogue states, message transcripts, and collected patient details.

### 3. Bookings, Telephony & Alerts
* **Outbound Call Requests**: Manages jobs queued by the system to initiate automated outbound phone calls.
* **Outbound Calls**: Records individual telephony dialing attempts, provider Call SIDs, and call status lifecycle events.
* **Appointments**: Represents confirmed bookings linking the patient, reserved time slot, consultation type, and originating conversation.
* **Notifications**: Handles delivery of SMS and email confirmation receipts and reminders to patients.

---

### Core Enums

* **`ChannelType`**: `voice`, `outbound_call`, `chat`
* **`AppointmentStatus`**: `booked`
* **`ConversationState`**: `started`, `identifying_patient`, `collecting_details`, `suggesting_slots`, `reconfirming`, `booked`, `confirmation_sent`, `abandoned`, `failed`, `handed_to_front_desk`, `no_answer`, `busy`, `retry_scheduled`
* **`OutcomeType`**: `booked`, `abandoned`, `failed`, `handed_to_front_desk`, `not_reached`, `wrong_person`
* **`ConfirmationStatusType`**: `pending`, `sent`, `retrying`, `failed`, `flagged`
* **`OutboundCallRequestStatus`**: `waiting`, `processing`, `started`, `completed`, `cancelled`, `expired`, `failed`
* **`CallStatus`**: `dialing`, `no_answer`, `busy`, `answered`, `failed`
* **`NotificationChannel`**: `sms`, `email`
* **`NotificationStatus`**: `pending`, `sent`, `failed`

---

### Model Architecture Principles

* **Directional Foreign Keys Only**: Relationships exist only where a foreign key column is defined (e.g. `Appointment` points to `Patient`, `Slot`, `AppointmentType`, and `Conversation`).
* **Zero Circular Imports**: Independent tables (like `Patient`, `Location`, `AppointmentType`) have zero imports of other models.
* **No Redundant Collections**: Tables avoid heavy reverse collections that load thousands of historical records into memory.
* **Database-Level Concurrency Protection**:
  * **Double Booking Prevention**: Enforced via `unique=True` on `appointments.slot_id` and unique `(provider_id, start_time)` on `slots`.
  * **Webhook Idempotency**: Enforced via `unique=True` on `outbound_calls.provider_call_id` and composite uniqueness on `(call_request_id, attempt_number)`.
  * **Open Request Deduplication**: Partial unique index on `outbound_call_requests.number_to_call` preventing concurrent open outreach jobs for the same recipient.
  * **Patient Identity Fast Lookups**: Composite index on `patients(full_name, date_of_birth)`.
  * **Cascade Protection**: Slots enforce `RESTRICT` on provider deletion so doctor availability and booking histories are never accidentally purged.

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
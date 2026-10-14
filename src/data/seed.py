"""
iClinic Demo Seed Data for PostgreSQL + SQLAlchemy 2.x (Async).

Seeds the 5 initial static tables:
  1. locations (4 Chennai branches)
  2. providers (16 doctors, 4 per branch)
  3. appointment_types (all strictly 30 minutes with prep instructions)
  4. slots (1,344 30-minute slots; derived via provider -> location)
  5. patients (sample test patients for outbound calls & verification)

Date range: 25-31 October 2026 (inclusive), Asia/Kolkata (IST).
Daily windows: 09:00-12:00 and 14:00-17:00 (30-minute slots).

Run:
    uv run python -m src.data.seed
"""

import asyncio
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import text
from src.data.clients.postgres import engine

# Indian Standard Time (UTC+05:30) - compatible with Windows without needing tzdata package
IST = timezone(timedelta(hours=5, minutes=30), name="IST")
SEED_BY = "data_loader"

# ─────────────────────────────────────────────────────────────────────────────
# 1. LOCATIONS (4 Chennai Branches)
# ─────────────────────────────────────────────────────────────────────────────
LOCATIONS = [
    ("Anna Nagar Branch", "Plot 12, 2nd Avenue, Anna Nagar, Chennai, Tamil Nadu 600040"),
    ("T. Nagar Branch", "No. 45, North Usman Road, T. Nagar, Chennai, Tamil Nadu 600017"),
    ("Velachery Branch", "No. 8, 100 Feet Road, Velachery, Chennai, Tamil Nadu 600042"),
    ("Tambaram Branch", "No. 21, GST Road, Tambaram, Chennai, Tamil Nadu 600045"),
]

# ─────────────────────────────────────────────────────────────────────────────
# 2. PROVIDERS (4 Doctors per Branch = 16 Total)
# ─────────────────────────────────────────────────────────────────────────────
PROVIDERS = [
    # 1. Anna Nagar Branch
    ("Dr. Arjun Reddy", "General Medicine", "Anna Nagar Branch"),
    ("Dr. Meera Krishnan", "Pediatrics", "Anna Nagar Branch"),
    ("Dr. Rajesh Kannan", "Cardiology", "Anna Nagar Branch"),
    ("Dr. Shalini Sundaram", "Dermatology", "Anna Nagar Branch"),

    # 2. T. Nagar Branch
    ("Dr. Karthik Subramanian", "Orthopedics", "T. Nagar Branch"),
    ("Dr. Priya Nair", "Dermatology", "T. Nagar Branch"),
    ("Dr. Ashwin Balaji", "General Medicine", "T. Nagar Branch"),
    ("Dr. Deepa Venkat", "Gynecology", "T. Nagar Branch"),

    # 3. Velachery Branch
    ("Dr. Sandeep Kumar", "Cardiology", "Velachery Branch"),
    ("Dr. Ananya Iyer", "Gynecology", "Velachery Branch"),
    ("Dr. Suresh Chandran", "Orthopedics", "Velachery Branch"),
    ("Dr. Divya Rangarajan", "Pediatrics", "Velachery Branch"),

    # 4. Tambaram Branch
    ("Dr. Vivek Sharma", "ENT", "Tambaram Branch"),
    ("Dr. Lakshmi Narayanan", "General Medicine", "Tambaram Branch"),
    ("Dr. Harish Gautham", "Cardiology", "Tambaram Branch"),
    ("Dr. Nithya Raman", "Dermatology", "Tambaram Branch"),
]

# ─────────────────────────────────────────────────────────────────────────────
# 3. APPOINTMENT TYPES (All strictly 30 minutes with instructions - FR-12)
# ─────────────────────────────────────────────────────────────────────────────
APPOINTMENT_TYPES = [
    (
        "General Consultation",
        30,
        "Please arrive 10 minutes early. Bring relevant previous prescriptions or medical reports."
    ),
    (
        "Follow-up Consultation",
        30,
        "Please bring your previous visit summary, current medication list, and any reports requested during your last visit."
    ),
    (
        "Specialist Consultation",
        30,
        "Please bring relevant medical records, investigation reports, and current prescriptions. Arrive 10 minutes early."
    ),
    (
        "Preventive Health Check",
        30,
        "Please bring previous health reports if available. Ask the clinic in advance whether fasting or preparation is required for your selected tests."
    ),
    (
        "Dental Consultation",
        30,
        "Please arrive 10 minutes early and bring relevant dental records or recent dental X-rays if available."
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# 4. SAMPLE PATIENTS (For testing outbound calls & identity verification - FR-6)
# ─────────────────────────────────────────────────────────────────────────────
PATIENTS = [
    ("Surendra", date(2003, 12, 14), "+916303023283", "surendrareddy49175@gmail.com"),
    ("Sreekesh", date(2003, 1, 22), "+919494488909", "sreekesh@gmail.com"),
    ("Kiran", date(2004, 12, 25), "+919080628116", "kiranrohitht@gmail.com"),
    ("Ramya", date(2004,11,5), "+919344348174", "sudharamya2404@gmail.com"),
    ("Surendra", date(2004, 9, 3), "+919986251229", "surendra@gmail.com"),
]

DATE_START = date(2026, 10, 25)
DATE_END = date(2026, 10, 31)
SESSION_WINDOWS = [(time(9, 0), time(12, 0)), (time(14, 0), time(17, 0))]
SLOT_MINUTES = 30


async def get_or_create(connection, table: str, key_column: str, key_value, values: dict) -> int:
    """Helper to fetch existing row ID or insert if missing (idempotent + updates changes)."""
    query_result = await connection.execute(
        text(f"SELECT id FROM {table} WHERE {key_column} = :key_value ORDER BY id LIMIT 1"),
        {"key_value": key_value},
    )
    row = query_result.first()
    if row:
        record_id = int(row[0])
        update_columns = [f"{column_name} = :{column_name}" for column_name in values.keys() if column_name != key_column]
        if update_columns:
            row_values = dict(values)
            row_values["id"] = record_id
            row_values["updated_by"] = SEED_BY
            await connection.execute(
                text(f"UPDATE {table} SET {', '.join(update_columns)}, updated_at = NOW(), updated_by = :updated_by WHERE id = :id"),
                row_values,
            )
        return record_id

    row_values = dict(values)
    row_values["created_by"] = SEED_BY
    row_values["updated_by"] = SEED_BY
    columns = list(row_values.keys())
    sql_columns = ", ".join(columns)
    sql_values = ", ".join(f":{column_name}" for column_name in columns)

    insert_result = await connection.execute(
        text(f"INSERT INTO {table} ({sql_columns}) VALUES ({sql_values}) RETURNING id"),
        row_values,
    )
    return int(insert_result.scalar_one())


def iter_slots(day: date):
    """Generates 30-minute start and end timestamps for the day in IST."""
    for session_start, session_end in SESSION_WINDOWS:
        current_time = datetime.combine(day, session_start, tzinfo=IST)
        end_time = datetime.combine(day, session_end, tzinfo=IST)
        while current_time + timedelta(minutes=SLOT_MINUTES) <= end_time:
            yield current_time, current_time + timedelta(minutes=SLOT_MINUTES)
            current_time += timedelta(minutes=SLOT_MINUTES)


async def main(reset: bool = False):
    async with engine.begin() as connection:
        # 1. Verify tables exist
        required_tables = ("locations", "providers", "appointment_types", "slots", "patients")
        for table in required_tables:
            table_exists = (await connection.execute(
                text("SELECT to_regclass(:table_name)"),
                {"table_name": f"public.{table}"},
            )).scalar()
            if table_exists is None:
                raise RuntimeError(
                    f"[-] Required table public.{table} not found. Run Alembic migrations first."
                )

        # Optional reset: wipe seed data cleanly to reflect deletions and start fresh
        if reset:
            print("[*] --reset detected: Clearing previous seed records...")
            await connection.execute(
                text("TRUNCATE TABLE slots, patients, appointment_types, providers, locations RESTART IDENTITY CASCADE")
            )
            print("[+] Seed tables truncated and IDs reset to 1.\n")

        # 2. Seed Locations
        location_ids = {}
        for location_name, address in LOCATIONS:
            location_ids[location_name] = await get_or_create(
                connection, "locations", "name", location_name,
                {"name": location_name, "address": address, "is_active": True},
            )

        # 3. Seed Providers (linked to location_id)
        provider_ids = {}
        for full_name, specialty, location_name in PROVIDERS:
            location_id = location_ids[location_name]
            provider_ids[full_name] = await get_or_create(
                connection, "providers", "full_name", full_name,
                {
                    "full_name": full_name,
                    "specialty": specialty,
                    "location_id": location_id,
                    "is_active": True,
                },
            )

        # 4. Seed Appointment Types
        appointment_type_ids = {}
        for appointment_name, duration_minutes, instructions in APPOINTMENT_TYPES:
            appointment_type_ids[appointment_name] = await get_or_create(
                connection, "appointment_types", "name", appointment_name,
                {
                    "name": appointment_name,
                    "duration_minutes": duration_minutes,
                    "instructions": instructions,
                    "is_active": True,
                },
            )

        # 5. Seed Patients (Upsert: updates phone/email if patient exists, inserts if new)
        patients_added = 0
        patients_updated = 0
        for full_name, date_of_birth, phone, email in PATIENTS:
            patient_result = await connection.execute(
                text("SELECT id, phone, email FROM patients WHERE full_name = :full_name AND date_of_birth = :date_of_birth LIMIT 1"),
                {"full_name": full_name, "date_of_birth": date_of_birth},
            )
            patient_row = patient_result.first()
            if patient_row:
                existing_id, existing_phone, existing_email = patient_row[0], patient_row[1], patient_row[2]
                if existing_phone != phone or existing_email != email:
                    await connection.execute(
                        text("""
                            UPDATE patients
                            SET phone = :phone, email = :email, is_active = true,
                                updated_at = NOW(), updated_by = :updated_by
                            WHERE id = :id
                        """),
                        {
                            "id": existing_id,
                            "phone": phone,
                            "email": email,
                            "updated_by": SEED_BY,
                        },
                    )
                    patients_updated += 1
            else:
                await connection.execute(
                    text("""
                        INSERT INTO patients (
                            full_name, date_of_birth, phone, email, is_active,
                            created_by, updated_by
                        ) VALUES (
                            :full_name, :date_of_birth, :phone, :email, true,
                            :created_by, :updated_by
                        )
                    """),
                    {
                        "full_name": full_name,
                        "date_of_birth": date_of_birth,
                        "phone": phone,
                        "email": email,
                        "created_by": SEED_BY,
                        "updated_by": SEED_BY,
                    },
                )
                patients_added += 1

        # 6. Seed Slots (Clean Normalized: NO location_id column in slots)
        inserted_slots = 0
        current_day = DATE_START
        while current_day <= DATE_END:
            for provider_name, provider_id in provider_ids.items():
                for start_time, end_time in iter_slots(current_day):
                    source_ref = f"seed-v2:{provider_id}:{start_time.isoformat()}"

                    slot_result = await connection.execute(
                        text("""
                            SELECT id FROM slots
                            WHERE source_ref = :source_ref
                               OR (provider_id = :provider_id AND start_time = :start_time)
                            LIMIT 1
                        """),
                        {
                            "source_ref": source_ref,
                            "provider_id": provider_id,
                            "start_time": start_time,
                        },
                    )
                    existing_slot = slot_result.first()
                    if existing_slot:
                        continue

                    await connection.execute(
                        text("""
                            INSERT INTO slots (
                                provider_id, start_time, end_time,
                                source_ref, created_by, updated_by
                            ) VALUES (
                                :provider_id, :start_time, :end_time,
                                :source_ref, :created_by, :updated_by
                            )
                        """),
                        {
                            "provider_id": provider_id,
                            "start_time": start_time,
                            "end_time": end_time,
                            "source_ref": source_ref,
                            "created_by": SEED_BY,
                            "updated_by": SEED_BY,
                        },
                    )
                    inserted_slots += 1
            current_day += timedelta(days=1)

        print("\n==========================================")
        print("   iClinic Demo Seed Completed Successfully")
        print("==========================================")
        print(f"[+] Locations present:        {len(location_ids)}")
        print(f"[+] Providers present:        {len(provider_ids)}")
        print(f"[+] Appointment types:        {len(appointment_type_ids)}")
        print(f"[+] Patients total in seed:   {len(PATIENTS)}")
        print(f"[+] New patients added:       {patients_added}")
        print(f"[+] Existing patients updated:{patients_updated}")
        print(f"[+] New slots generated:      {inserted_slots}")
        print(f"[+] Date range:               {DATE_START} to {DATE_END}")
        print("[+] Slot duration:            30 minutes (09:00-12:00 & 14:00-17:00 IST)")
        print("==========================================\n")


def preview_slots():
    """Prints a terminal preview of the data to be seeded without touching the database."""
    print("\n=======================================================")
    print("   iClinic Demo Seed: PREVIEW MODE (NO DATABASE WRITES)")
    print("=======================================================")
    print(f"\n[+] LOCATIONS ({len(LOCATIONS)}):")
    for location_name, address in LOCATIONS:
        print(f"   * {location_name} -> {address}")

    print(f"\n[+] PROVIDERS ({len(PROVIDERS)}):")
    for full_name, specialty, branch_name in PROVIDERS:
        print(f"   * {full_name} ({specialty}) @ {branch_name}")

    print(f"\n[+] APPOINTMENT TYPES ({len(APPOINTMENT_TYPES)}):")
    for appointment_name, duration_minutes, _ in APPOINTMENT_TYPES:
        print(f"   * {appointment_name} ({duration_minutes} mins)")

    print(f"\n[+] PATIENTS ({len(PATIENTS)}):")
    for full_name, date_of_birth, phone, email in PATIENTS:
        print(f"   * {full_name} (DOB: {date_of_birth}, Phone: {phone}, Email: {email})")

    print(f"\n[+] SLOTS SCHEDULE ({DATE_START} to {DATE_END}):")
    print("   Daily Windows: 09:00-12:00 & 14:00-17:00 IST (30-min intervals)\n")

    total_slots = 0
    current_day = DATE_START
    while current_day <= DATE_END:
        day_slots = list(iter_slots(current_day))
        slots_per_doctor = len(day_slots)
        total_day_slots = slots_per_doctor * len(PROVIDERS)
        total_slots += total_day_slots
        print(f"   - {current_day.strftime('%A, %d %b %Y')}: {slots_per_doctor} slots/doctor x {len(PROVIDERS)} doctors = {total_day_slots} slots")
        
        # Show first doctor's slots as a sample
        if current_day == DATE_START:
            first_doctor_name = PROVIDERS[0][0]
            print(f"      Sample time slots for {first_doctor_name}:")
            for start_time, end_time in day_slots:
                print(f"        * {start_time.strftime('%I:%M %p')} to {end_time.strftime('%I:%M %p')} IST")
        current_day += timedelta(days=1)

    print("\n=======================================================")
    print(f"[+] TOTAL SLOTS THAT WILL BE CREATED: {total_slots}")
    print("=======================================================\n")


if __name__ == "__main__":
    import sys
    if "--preview" in sys.argv or "--dry-run" in sys.argv or "check" in sys.argv:
        preview_slots()
    else:
        reset_mode = "--reset" in sys.argv
        asyncio.run(main(reset=reset_mode))


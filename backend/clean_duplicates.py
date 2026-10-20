import asyncio
# pyrefly: ignore[missing-import]
from sqlalchemy import text
from src.data.clients.postgres import AsyncSessionLocal


async def clean_duplicates():
    async with AsyncSessionLocal() as session:
        # 1. Merge Hemanth
        res = await session.execute(
            text("SELECT id FROM patients WHERE full_name ILIKE 'Hemanth' ORDER BY created_at")
        )
        hemanth_ids = [r[0] for r in res.fetchall()]
        if len(hemanth_ids) > 1:
            primary_id = hemanth_ids[0]
            for dup_id in hemanth_ids[1:]:
                # If duplicate has an active appointment and primary already has one, cancel the duplicate's active appointment
                has_primary_active = await session.scalar(
                    text("SELECT COUNT(*) FROM appointments WHERE patient_id = :pri AND status IN ('booked', 'rescheduled')"),
                    {"pri": primary_id},
                )
                if has_primary_active:
                    # Cancel duplicate's booked appointment before reassigning
                    await session.execute(
                        text("UPDATE appointments SET status = 'cancelled' WHERE patient_id = :dup AND status IN ('booked', 'rescheduled')"),
                        {"dup": dup_id},
                    )
                await session.execute(
                    text("UPDATE appointments SET patient_id = :pri WHERE patient_id = :dup"),
                    {"pri": primary_id, "dup": dup_id},
                )
                await session.execute(
                    text("UPDATE conversations SET patient_id = :pri WHERE patient_id = :dup"),
                    {"pri": primary_id, "dup": dup_id},
                )
                await session.execute(
                    text("DELETE FROM patients WHERE id = :dup"),
                    {"dup": dup_id},
                )
            await session.execute(
                text(
                    "UPDATE patients SET date_of_birth = '2004-07-17', "
                    "email = 'hemanth@gmail.com', phone = '+918919545828' WHERE id = :pri"
                ),
                {"pri": primary_id},
            )
            print(f"Merged {len(hemanth_ids)-1} duplicate Hemanth records into {primary_id}")

        # 2. Merge Surendra dummy records into primary
        res = await session.execute(
            text("SELECT id FROM patients WHERE phone = '+916303023283' LIMIT 1")
        )
        sur_row = res.first()
        if sur_row:
            sur_id = sur_row[0]
            res_dummies = await session.execute(
                text(
                    "SELECT id FROM patients WHERE (full_name ILIKE 'Surendra' "
                    "AND (phone = '' OR phone IS NULL)) OR full_name ILIKE '%reschedule%'"
                )
            )
            for r in res_dummies.fetchall():
                dup_id = r[0]
                # Cancel any active appointments on dummy record and release slots
                dup_appts = await session.execute(
                    text("SELECT id, slot_id FROM appointments WHERE patient_id = :dup AND status IN ('booked', 'rescheduled')"),
                    {"dup": dup_id},
                )
                for a_id, s_id in dup_appts.fetchall():
                    await session.execute(text("UPDATE slots SET status = 'available', reserved_until = NULL WHERE id = :sid"), {"sid": s_id})
                    await session.execute(text("UPDATE appointments SET status = 'cancelled' WHERE id = :aid"), {"aid": a_id})

                await session.execute(
                    text("UPDATE appointments SET patient_id = :pri WHERE patient_id = :dup"),
                    {"pri": sur_id, "dup": dup_id},
                )
                await session.execute(
                    text("UPDATE conversations SET patient_id = :pri WHERE patient_id = :dup"),
                    {"pri": sur_id, "dup": dup_id},
                )
                await session.execute(
                    text("DELETE FROM patients WHERE id = :dup"),
                    {"dup": dup_id},
                )
            print(f"Merged dummy Surendra records into {sur_id}")

        # 3. Merge Kiran dummy records into primary
        res = await session.execute(
            text("SELECT id FROM patients WHERE phone = '+919080628116' LIMIT 1")
        )
        kiran_row = res.first()
        if kiran_row:
            kiran_id = kiran_row[0]
            res_dummies = await session.execute(
                text(
                    "SELECT id FROM patients WHERE full_name ILIKE 'Kiran' "
                    "AND (phone = '' OR phone IS NULL)"
                )
            )
            for r in res_dummies.fetchall():
                dup_id = r[0]
                dup_appts = await session.execute(
                    text("SELECT id, slot_id FROM appointments WHERE patient_id = :dup AND status IN ('booked', 'rescheduled')"),
                    {"dup": dup_id},
                )
                for a_id, s_id in dup_appts.fetchall():
                    await session.execute(text("UPDATE slots SET status = 'available', reserved_until = NULL WHERE id = :sid"), {"sid": s_id})
                    await session.execute(text("UPDATE appointments SET status = 'cancelled' WHERE id = :aid"), {"aid": a_id})

                await session.execute(
                    text("UPDATE appointments SET patient_id = :pri WHERE patient_id = :dup"),
                    {"pri": kiran_id, "dup": dup_id},
                )
                await session.execute(
                    text("UPDATE conversations SET patient_id = :pri WHERE patient_id = :dup"),
                    {"pri": kiran_id, "dup": dup_id},
                )
                await session.execute(
                    text("DELETE FROM patients WHERE id = :dup"),
                    {"dup": dup_id},
                )
            print(f"Merged dummy Kiran records into {kiran_id}")

        # 4. Merge Sai dummy records into Sai Kumar
        res = await session.execute(
            text("SELECT id FROM patients WHERE phone = '+919811223344' LIMIT 1")
        )
        sai_row = res.first()
        if sai_row:
            sai_id = sai_row[0]
            res_dummies = await session.execute(
                text(
                    "SELECT id FROM patients WHERE full_name ILIKE 'Sai' "
                    "AND (phone = '' OR phone IS NULL)"
                )
            )
            for r in res_dummies.fetchall():
                dup_id = r[0]
                dup_appts = await session.execute(
                    text("SELECT id, slot_id FROM appointments WHERE patient_id = :dup AND status IN ('booked', 'rescheduled')"),
                    {"dup": dup_id},
                )
                for a_id, s_id in dup_appts.fetchall():
                    await session.execute(text("UPDATE slots SET status = 'available', reserved_until = NULL WHERE id = :sid"), {"sid": s_id})
                    await session.execute(text("UPDATE appointments SET status = 'cancelled' WHERE id = :aid"), {"aid": a_id})

                await session.execute(
                    text("UPDATE appointments SET patient_id = :pri WHERE patient_id = :dup"),
                    {"pri": sai_id, "dup": dup_id},
                )
                await session.execute(
                    text("UPDATE conversations SET patient_id = :pri WHERE patient_id = :dup"),
                    {"pri": sai_id, "dup": dup_id},
                )
                await session.execute(
                    text("DELETE FROM patients WHERE id = :dup"),
                    {"dup": dup_id},
                )
            print(f"Merged dummy Sai records into {sai_id}")

        # 5. Fix rescheduled appointments
        await session.execute(
            text(
                "UPDATE appointments SET status = 'rescheduled' "
                "WHERE id IN (SELECT old_appointment_id FROM appointment_reschedules) "
                "AND status = 'booked'"
            )
        )

        await session.commit()
        print("Database deduplication committed successfully.")


if __name__ == "__main__":
    asyncio.run(clean_duplicates())

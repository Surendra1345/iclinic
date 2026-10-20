import asyncio
from src.data.clients.postgres import AsyncSessionLocal
from sqlalchemy import select
from src.data.models.postgres.slot import Slot
from src.data.models.postgres.provider import Provider

async def check():
    async with AsyncSessionLocal() as db:
        doc = (await db.execute(select(Provider).where(Provider.full_name.ilike('%Ashwin%')))).scalar_one_or_none()
        print('Doctor:', doc.full_name if doc else None, doc.id if doc else None)
        if doc:
            slots = (await db.execute(select(Slot).where(Slot.provider_id == doc.id).order_by(Slot.start_time))).scalars().all()
            for s in slots:
                print(f'Slot {s.id}: {s.start_time.strftime("%A %Y-%m-%d %I:%M %p %Z")} Status: {s.status}')

if __name__ == '__main__':
    asyncio.run(check())

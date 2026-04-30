import asyncio
from database import create_pool
from ml.trainer import train_for_user

async def main():
    pool = await create_pool()
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT user_id FROM users")
                users = [row[0] for row in await cur.fetchall()]
            for uid in users:
                print(f"Training models for user {uid}...")
                await train_for_user(uid, conn)
                print(f"Done user {uid}.")
    finally:
        await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
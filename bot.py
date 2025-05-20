import asyncio
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from database import init_db
from aiogram.fsm.storage.memory import MemoryStorage

from handlers.registration import router as registration_router
from handlers.admin import router as admin_router
from handlers.boss import router as boss_router
from handlers.employee import router as employee_router

# Импорт планировщика
from reminder_scheduler import start_reminder_scheduler

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

dp.include_router(registration_router)
dp.include_router(admin_router)
dp.include_router(boss_router)
dp.include_router(employee_router)

async def main():
    await init_db()
    # Запуск планировщика напоминаний
    start_reminder_scheduler(bot)
    print("[DEBUG] Планировщик напоминаний запущен")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main()) 
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import async_session, MeetingReminder, User, Meeting, MeetingParticipant
from sqlalchemy.future import select
from datetime import datetime
from aiogram import Bot
import asyncio

async def send_reminders(bot: Bot):
    async with async_session() as session:
        now = datetime.now()
        print(f"[DEBUG] Проверка напоминаний: now={now}")
        result = await session.execute(
            select(MeetingReminder).where(MeetingReminder.remind_at <= now, MeetingReminder.sent == False)
        )
        reminders = result.scalars().all()
        print(f"[DEBUG] Найдено напоминаний к отправке: {len(reminders)}")
        for reminder in reminders:
            print(f"[DEBUG] Напоминание: id={reminder.id}, meeting_id={reminder.meeting_id}, user_id={reminder.user_id}, remind_at={reminder.remind_at}, sent={reminder.sent}")
            # Проверяем статус участия
            part_result = await session.execute(
                select(MeetingParticipant).where(
                    MeetingParticipant.meeting_id == reminder.meeting_id,
                    MeetingParticipant.user_id == reminder.user_id
                )
            )
            participant = part_result.scalar_one_or_none()
            if not participant or participant.status != 'accepted':
                print(f"[DEBUG] Напоминание не отправлено: статус участия не 'accepted' (status={getattr(participant, 'status', None)})")
                continue
            # Получаем пользователя и совещание
            user_result = await session.execute(select(User).where(User.id == reminder.user_id))
            user = user_result.scalar_one_or_none()
            meeting_result = await session.execute(select(Meeting).where(Meeting.id == reminder.meeting_id))
            meeting = meeting_result.scalar_one_or_none()
            if user and meeting and user.telegram_id:
                try:
                    await bot.send_message(
                        user.telegram_id,
                        f'Напоминание о совещании "{meeting.topic}"\nДата: {meeting.datetime.strftime("%d.%m.%Y %H:%M")}'
                    )
                    reminder.sent = True
                    await session.commit()
                    print(f"[DEBUG] Напоминание отправлено пользователю {user.telegram_id}")
                except Exception as e:
                    print(f'[ERROR] Не удалось отправить напоминание: {e}')
            else:
                print(f"[ERROR] Не удалось найти пользователя или совещание для напоминания id={reminder.id}")

scheduler = AsyncIOScheduler()

def start_reminder_scheduler(bot: Bot):
    scheduler.add_job(send_reminders, 'interval', seconds=60, args=[bot])
    scheduler.start() 
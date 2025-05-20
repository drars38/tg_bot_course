from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from states import EmployeeQuestion, DeclineMeeting
from database import async_session, User, Meeting, UserRole, MeetingParticipant, MeetingReminder, MeetingNote
from sqlalchemy.future import select
from keyboards import kb_employee
from aiogram.fsm.state import StatesGroup, State
from datetime import datetime, timedelta
from services.user_service import check_user_role

router = Router()

class ReminderStates(StatesGroup):
    waiting_minutes = State()
    waiting_meeting_id = State()

class EmployeeMeetingStates(StatesGroup):
    waiting_note = State()
    waiting_reminder = State()

@router.message(F.text == 'Мои приглашения')
async def show_my_invitations(message: types.Message):
    if not await check_user_role(message, UserRole.employee):
        return
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        if not user:
            await message.answer('Ошибка: вы не зарегистрированы.', reply_markup=kb_employee)
            return
        parts_result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.user_id == user.id, MeetingParticipant.status == 'pending'))
        parts = parts_result.scalars().all()
        if not parts:
            await message.answer('У вас нет новых приглашений.', reply_markup=kb_employee)
            return
        for p in parts:
            meeting_result = await session.execute(select(Meeting).where(Meeting.id == p.meeting_id))
            meeting = meeting_result.scalar_one_or_none()
            if meeting:
                kb = types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [types.InlineKeyboardButton(text='Принять', callback_data=f'meeting_accept_{meeting.id}')],
                        [types.InlineKeyboardButton(text='Отклонить', callback_data=f'meeting_decline_{meeting.id}')]
                    ]
                )
                await message.answer(f'Приглашение: {meeting.topic}\nДата: {meeting.datetime.strftime("%d.%m.%Y %H:%M")}', reply_markup=kb)

@router.message(F.text == 'Мои совещания')
async def show_my_accepted_meetings(message: types.Message):
    if not await check_user_role(message, UserRole.employee):
        return
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        if not user:
            await message.answer('Ошибка: вы не зарегистрированы.', reply_markup=kb_employee)
            return
        parts_result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.user_id == user.id, MeetingParticipant.status == 'accepted'))
        parts = parts_result.scalars().all()
        if not parts:
            await message.answer('У вас нет принятых совещаний.', reply_markup=kb_employee)
            return
        for p in parts:
            meeting_result = await session.execute(select(Meeting).where(Meeting.id == p.meeting_id))
            meeting = meeting_result.scalar_one_or_none()
            if meeting:
                await message.answer(f'Совещание: {meeting.topic}\nДата: {meeting.datetime.strftime("%d.%m.%Y %H:%M")}', reply_markup=kb_employee)

@router.message(F.text == 'Задать вопрос начальнику')
async def ask_boss_start(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.employee, state):
        return
    await message.answer('Введите ваш вопрос начальнику:')
    await state.set_state(EmployeeQuestion.waiting_question)

@router.message(EmployeeQuestion.waiting_question)
async def send_question_to_boss(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.employee, state):
        return
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        if not user:
            await message.answer('Ошибка: вы не зарегистрированы.', reply_markup=kb_employee)
            await state.clear()
            return
        # Ищем начальника по отделу
        boss_result = await session.execute(select(User).where(User.department == user.department, User.role == UserRole('начальник')))
        boss = boss_result.scalar_one_or_none()
        if not boss:
            await message.answer('В вашем отделе не найден начальник.', reply_markup=kb_employee)
            await state.clear()
            return
        try:
            kb = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text='Ответить', callback_data=f'answer_employee_{user.id}')]
                ]
            )
            await message.bot.send_message(boss.telegram_id, f'Вопрос от сотрудника {user.fio}:\n{message.text}', reply_markup=kb)
            await message.answer('Ваш вопрос отправлен начальнику.', reply_markup=kb_employee)
        except Exception:
            await message.answer('Ошибка при отправке вопроса начальнику.', reply_markup=kb_employee)
        await state.clear()

@router.message(F.text.startswith('Совещание:'))
async def show_meeting_details(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.employee, state):
        return
    # Пример: "Совещание: Тема\nДата: 01.01.2024 12:00"
    # Здесь нужно получить meeting_id по теме и дате (или хранить id в callback_data)
    # Для простоты примера — парсим тему
    topic = message.text.split(':', 1)[1].split('\n')[0].strip()
    async with async_session() as session:
        result = await session.execute(select(Meeting).where(Meeting.topic == topic))
        meeting = result.scalar_one_or_none()
        if not meeting:
            await message.answer('Совещание не найдено.')
            return
        # Кнопка установить напоминание
        kb = types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton(text='Установить напоминание')]],
            resize_keyboard=True
        )
        await state.update_data(meeting_id=meeting.id)
        await message.answer('Детали совещания. Вы можете установить напоминание.', reply_markup=kb)

@router.message(F.text == 'Установить напоминание')
async def ask_reminder_time(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.employee, state):
        return
    await message.answer('За сколько минут до совещания напомнить? (5, 10, 15, 30, 60 или введите своё число)')
    await state.set_state(ReminderStates.waiting_minutes)

@router.message(ReminderStates.waiting_minutes)
async def set_reminder_time(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.employee, state):
        return
    try:
        minutes = int(message.text.strip())
        if minutes <= 0:
            raise ValueError
    except Exception:
        await message.answer('Введите положительное число минут!')
        return
    data = await state.get_data()
    meeting_id = data.get('meeting_id')
    async with async_session() as session:
        result = await session.execute(select(Meeting).where(Meeting.id == meeting_id))
        meeting = result.scalar_one_or_none()
        if not meeting:
            await message.answer('Совещание не найдено.')
            await state.clear()
            return
        remind_at = meeting.datetime - timedelta(minutes=minutes)
        # Сохраняем напоминание
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        reminder = MeetingReminder(meeting_id=meeting.id, user_id=user.id, remind_at=remind_at)
        session.add(reminder)
        await session.commit()
        await message.answer(f'Напоминание установлено за {minutes} минут до совещания.')
        # Здесь можно запланировать отправку (через APScheduler или create_task)
    await state.clear()

@router.callback_query(lambda c: c.data.startswith('meeting_accept_'))
async def meeting_accept_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await check_user_role(callback, UserRole.employee, state):
        return
    meeting_id = int(callback.data.split('_')[-1])
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        part_result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id, MeetingParticipant.user_id == user.id))
        participant = part_result.scalar_one_or_none()
        if participant:
            participant.status = 'accepted'
            await session.commit()
            await callback.answer('Вы приняли приглашение!')
            await callback.message.edit_reply_markup()
        else:
            await callback.answer('Ошибка: приглашение не найдено.', show_alert=True)

@router.callback_query(lambda c: c.data.startswith('meeting_decline_'))
async def meeting_decline_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await check_user_role(callback, UserRole.employee, state):
        return
    meeting_id = int(callback.data.split('_')[-1])
    await state.update_data(meeting_id=meeting_id)
    await callback.message.answer('Пожалуйста, введите причину отказа:')
    await state.set_state(DeclineMeeting.waiting_reason)
    await callback.answer()

@router.message(DeclineMeeting.waiting_reason)
async def decline_reason_entered(message: types.Message, state: FSMContext):
    data = await state.get_data()
    meeting_id = data.get('meeting_id')
    user_id = message.from_user.id
    reason = message.text
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = result.scalar_one_or_none()
        part_result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id, MeetingParticipant.user_id == user.id))
        participant = part_result.scalar_one_or_none()
        if participant:
            participant.status = 'declined'
            participant.decline_reason = reason
            await session.commit()
        # Получаем совещание и организатора
        meeting_result = await session.execute(select(Meeting).where(Meeting.id == meeting_id))
        meeting = meeting_result.scalar_one_or_none()
        boss_result = await session.execute(select(User).where(User.id == meeting.creator_id))
        boss = boss_result.scalar_one_or_none()
        if boss:
            kb = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text='Принять причину', callback_data=f'accept_reason_{meeting_id}_{user.id}')],
                    [types.InlineKeyboardButton(text='Отклонить причину', callback_data=f'reject_reason_{meeting_id}_{user.id}')]
                ]
            )
            try:
                await message.bot.send_message(boss.telegram_id, f'Пользователь {user.fio} отклонил участие в совещании "{meeting.topic}".\nПричина: {reason}', reply_markup=kb)
            except Exception:
                pass
    await message.answer('Ваша причина отправлена организатору. Ожидайте решения.')
    await state.clear()

@router.message(F.text == 'Мои совещания (я участник)')
async def show_my_participated_meetings(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.employee):
        return
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        if not user:
            await message.answer('Ошибка: вы не зарегистрированы.', reply_markup=kb_employee)
            return
        parts_result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.user_id == user.id, MeetingParticipant.status == 'accepted'))
        parts = parts_result.scalars().all()
        if not parts:
            await message.answer('У вас нет совещаний, где вы участник.', reply_markup=kb_employee)
            return
        for p in parts:
            meeting_result = await session.execute(select(Meeting).where(Meeting.id == p.meeting_id))
            meeting = meeting_result.scalar_one_or_none()
            if not meeting:
                continue
            # Напоминание
            reminder_result = await session.execute(select(MeetingReminder).where(MeetingReminder.meeting_id == meeting.id, MeetingReminder.user_id == user.id))
            reminder = reminder_result.scalar_one_or_none()
            reminder_text = f'\nНапоминание: {reminder.remind_at.strftime("%d.%m.%Y %H:%M")}' if reminder else ''
            # Заметки
            notes_result = await session.execute(select(MeetingNote).where(MeetingNote.meeting_id == meeting.id))
            notes = notes_result.scalars().all()
            notes_text = ''
            if notes:
                notes_text = '\nЗаметки:'
                for note in notes:
                    author_result = await session.execute(select(User).where(User.id == note.author_id))
                    author = author_result.scalar_one_or_none()
                    author_name = author.fio if author else 'Неизвестно'
                    local_time = note.created_at + timedelta(hours=8)
                    notes_text += f"\n— {author_name} ({local_time.strftime('%d.%m.%Y %H:%M')}): {note.text}"
            # Inline-кнопки
            inline_kb = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text='Добавить заметку', callback_data=f'add_note_{meeting.id}')],
                    [types.InlineKeyboardButton(text='Добавить напоминание', callback_data=f'add_reminder_{meeting.id}')]
                ]
            )
            await message.answer(f'Совещание: {meeting.topic}\nДата: {meeting.datetime.strftime("%d.%m.%Y %H:%M")}\nДлительность: {meeting.duration} минут{reminder_text}{notes_text}', reply_markup=inline_kb)

@router.callback_query(lambda c: c.data.startswith('add_note_'))
async def add_note_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await check_user_role(callback, UserRole.employee, state):
        return
    meeting_id = int(callback.data.split('_')[-1])
    # Проверка даты совещания
    async with async_session() as session:
        meeting_result = await session.execute(select(Meeting).where(Meeting.id == meeting_id))
        meeting = meeting_result.scalar_one_or_none()
        if meeting and meeting.datetime > datetime.now():
            await callback.message.answer('Заметки можно добавлять только после наступления даты совещания.')
            await callback.answer()
            return
    await state.update_data(meeting_id=meeting_id)
    await callback.message.answer('Введите текст заметки:')
    await state.set_state(EmployeeMeetingStates.waiting_note)
    await callback.answer()

@router.message(EmployeeMeetingStates.waiting_note)
async def save_meeting_note(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.employee, state):
        return
    data = await state.get_data()
    meeting_id = data.get('meeting_id')
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        note = MeetingNote(meeting_id=meeting_id, author_id=user.id, text=message.text)
        session.add(note)
        await session.commit()
        await message.answer('Заметка добавлена!')
    await state.clear()

@router.callback_query(lambda c: c.data.startswith('add_reminder_'))
async def add_reminder_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await check_user_role(callback, UserRole.employee, state):
        return
    meeting_id = int(callback.data.split('_')[-1])
    # Проверка статуса участия
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        part_result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id, MeetingParticipant.user_id == user.id))
        participant = part_result.scalar_one_or_none()
        if not participant or participant.status != 'accepted':
            await callback.message.answer('Вы можете установить напоминание только после подтверждения участия в совещании.')
            await callback.answer()
            return
    await state.update_data(meeting_id=meeting_id)
    await callback.message.answer('За сколько минут до совещания напомнить? (например, 5, 10, 15, 30, 60)')
    await state.set_state(EmployeeMeetingStates.waiting_reminder)
    await callback.answer()

@router.message(EmployeeMeetingStates.waiting_reminder)
async def save_meeting_reminder(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.employee, state):
        return
    try:
        minutes = int(message.text.strip())
        if minutes <= 0:
            raise ValueError
    except Exception:
        await message.answer('Введите положительное число минут!')
        return
    data = await state.get_data()
    meeting_id = data.get('meeting_id')
    async with async_session() as session:
        result = await session.execute(select(Meeting).where(Meeting.id == meeting_id))
        meeting = result.scalar_one_or_none()
        if not meeting:
            await message.answer('Совещание не найдено.')
            await state.clear()
            return
        remind_at = meeting.datetime - timedelta(minutes=minutes)
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        # Проверяем, есть ли уже напоминание
        reminder_result = await session.execute(select(MeetingReminder).where(MeetingReminder.meeting_id == meeting.id, MeetingReminder.user_id == user.id))
        reminder = reminder_result.scalar_one_or_none()
        if reminder:
            reminder.remind_at = remind_at
        else:
            reminder = MeetingReminder(meeting_id=meeting.id, user_id=user.id, remind_at=remind_at)
            session.add(reminder)
        await session.commit()
        await message.answer(f'Напоминание установлено за {minutes} минут до совещания.')
    await state.clear() 
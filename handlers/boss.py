from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from states import CreateMeeting, BossAnswer
from database import async_session, User, Meeting, UserRole, MeetingParticipant, MeetingReminder, MeetingNote
from sqlalchemy.future import select
from sqlalchemy import delete
from keyboards import kb_boss, get_participants_keyboard
from datetime import datetime, timedelta
from services.user_service import check_user_role
from aiogram.fsm.state import StatesGroup, State

router = Router()

class BossMeetingStates(StatesGroup):
    waiting_note = State()
    waiting_reminder = State()
    waiting_edit_field = State()
    waiting_new_topic = State()
    waiting_new_datetime = State()
    waiting_edit_participants = State()

@router.message(F.text == 'Создать совещание')
async def create_meeting_start(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.boss, state):
        return
    await message.answer('Введите тему совещания:')
    await state.set_state(CreateMeeting.topic)

@router.message(CreateMeeting.topic)
async def create_meeting_topic(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.boss, state):
        return
    await state.update_data(topic=message.text)
    await message.answer('Введите дату и время совещания в формате ДД.ММ.ГГГГ ЧЧ:ММ:')
    await state.set_state(CreateMeeting.datetime)

@router.message(CreateMeeting.datetime)
async def create_meeting_datetime(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.boss, state):
        return
    try:
        dt = datetime.strptime(message.text, '%d.%m.%Y %H:%M')
    except ValueError:
        await message.answer('Некорректный формат! Введите дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ')
        return
    if dt < datetime.now():
        await message.answer('Нельзя создавать совещание в прошлом! Введите корректную дату и время.')
        return
    await state.update_data(datetime=dt)
    await message.answer('Введите длительность совещания в минутах (например, 60):')
    await state.set_state(CreateMeeting.duration)

@router.message(CreateMeeting.duration)
async def create_meeting_duration(message: types.Message, state: FSMContext):
    try:
        duration = int(message.text.strip())
        if duration <= 0:
            raise ValueError
    except Exception:
        await message.answer('Введите положительное число минут!')
        return
    await state.update_data(duration=duration)
    # Получаем отдел начальника
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        boss = result.scalar_one_or_none()
        if not boss:
            await message.answer('Ошибка: вы не зарегистрированы.')
            await state.clear()
            return
        department = boss.department
        # Получаем сотрудников отдела
        result = await session.execute(select(User).where(User.department == department, User.role == UserRole('сотрудник')))
        employees = result.scalars().all()
    if not employees:
        await message.answer('В вашем отделе нет сотрудников.')
        await state.clear()
        return
    await state.update_data(participants=[], department=department)
    kb = get_participants_keyboard(employees, [], mode='create')
    await message.answer('Выберите участников совещания (нажимайте по очереди, затем "Готово"):', reply_markup=kb)
    await state.set_state(CreateMeeting.participants)

@router.callback_query(lambda c: c.data.startswith('add_participant_'))
async def boss_add_participant_edit_callback(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    emp_id = int(callback.data.split('_')[-1])
    participants = data.get('participants', [])
    if emp_id in participants:
        participants.remove(emp_id)
    else:
        participants.append(emp_id)
    await state.update_data(participants=participants)
    # Получаем сотрудников отдела
    async with async_session() as session:
        result = await session.execute(select(User).where(User.department == data['department'], User.role == UserRole('сотрудник')))
        employees = result.scalars().all()
    # Определяем режим
    mode = 'edit' if 'meeting_id' in data else 'create'
    kb = get_participants_keyboard(employees, participants, mode=mode)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer('Изменено!')

# Новый обработчик для создания совещания
@router.callback_query(lambda c: c.data == 'participants_done_create')
async def participants_done_create_callback(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get('participants'):
        await callback.answer('Выберите хотя бы одного участника!', show_alert=True)
        return
    await callback.message.answer('Подтвердите создание совещания? (да/нет)')
    await state.set_state(CreateMeeting.confirm)
    await callback.answer()

# Переименованный обработчик для редактирования участников
@router.callback_query(lambda c: c.data == 'participants_done_edit')
async def boss_edit_participants_done_callback(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    meeting_id = data.get('meeting_id')
    new_participants = set(data.get('participants', []))
    async with async_session() as session:
        # Получаем текущих участников
        parts_result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id))
        current_parts = parts_result.scalars().all()
        current_ids = set(p.user_id for p in current_parts)
        # Удаляем участников, которых больше нет
        for p in current_parts:
            if p.user_id not in new_participants:
                await session.delete(p)
        # Добавляем новых участников
        for user_id in new_participants:
            if user_id not in current_ids:
                participant = MeetingParticipant(meeting_id=meeting_id, user_id=user_id, status='pending')
                session.add(participant)
        # Обновляем напоминания: удаляем старые, создаём новые за 5 минут до начала
        await session.execute(delete(MeetingReminder).where(MeetingReminder.meeting_id == meeting_id))
        meeting_result = await session.execute(select(Meeting).where(Meeting.id == meeting_id))
        meeting = meeting_result.scalar_one_or_none()
        # ОТЛАДКА: выводим meeting_id и найдено ли совещание
        if not meeting:
            await callback.message.answer(f'Отладка: совещание не найдено (meeting_id={meeting_id})')
            await state.clear()
            await callback.answer()
            return
        from datetime import timedelta
        for user_id in new_participants:
            remind_at = meeting.datetime - timedelta(minutes=5)
            reminder = MeetingReminder(meeting_id=meeting.id, user_id=user_id, remind_at=remind_at)
            session.add(reminder)
        await session.commit()
    await callback.message.answer('Список участников и напоминания обновлены!')
    await state.clear()
    await callback.answer()

@router.message(CreateMeeting.confirm)
async def create_meeting_confirm(message: types.Message, state: FSMContext, bot: Bot):
    if not await check_user_role(message, UserRole.boss, state):
        return
    data = await state.get_data()
    if 'topic' not in data:
        await message.answer('Ошибка: тема совещания не найдена. Пожалуйста, начните создание совещания заново.')
        await state.clear()
        return
    async with async_session() as session:
        # Получаем пользователя (начальника) по telegram_id
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        boss = result.scalar_one_or_none()
        meeting = Meeting(
            topic=data['topic'],
            datetime=data['datetime'],
            duration=data['duration'],
            creator_id=boss.id
        )
        session.add(meeting)
        await session.commit()
        await session.refresh(meeting)
        # ОТЛАДКА: выводим boss.id и список участников
        await message.answer(f'Отладка: boss.id={boss.id}, data[participants]={data["participants"]}')
        # Добавляем участников
        for user_id in data['participants']:
            participant = MeetingParticipant(meeting_id=meeting.id, user_id=user_id, status='pending')
            session.add(participant)
        # Создатель совещания автоматически подтверждает участие
        if boss.id not in data['participants']:
            participant = MeetingParticipant(meeting_id=meeting.id, user_id=boss.id, status='accepted')
            session.add(participant)
            await message.answer(f'Отладка: начальник добавлен как участник (user_id={boss.id})')
        else:
            part_result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting.id, MeetingParticipant.user_id == boss.id))
            participant = part_result.scalar_one_or_none()
            if participant:
                participant.status = 'accepted'
                await message.answer(f'Отладка: статус начальника обновлён на accepted (user_id={boss.id})')
        await session.commit()
        # Добавляем напоминания за 5 минут до начала
        for user_id in data['participants']:
            reminder_result = await session.execute(
                select(MeetingReminder).where(
                    MeetingReminder.meeting_id == meeting.id,
                    MeetingReminder.user_id == user_id
                )
            )
            reminder = reminder_result.scalar_one_or_none()
            remind_at = meeting.datetime - timedelta(minutes=5)
            if not reminder:
                reminder = MeetingReminder(meeting_id=meeting.id, user_id=user_id, remind_at=remind_at)
                session.add(reminder)
        await session.commit()
        # Рассылаем приглашения участникам
        for user_id in data['participants']:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                kb = types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [types.InlineKeyboardButton(text='Принять', callback_data=f'meeting_accept_{meeting.id}')],
                        [types.InlineKeyboardButton(text='Отклонить', callback_data=f'meeting_decline_{meeting.id}')]
                    ]
                )
                try:
                    await bot.send_message(user.telegram_id, f'Вас пригласили на совещание "{meeting.topic}" в {meeting.datetime.strftime("%d.%m.%Y %H:%M")}', reply_markup=kb)
                except Exception:
                    pass
    await message.answer('Совещание успешно создано!', reply_markup=kb_boss)
    await state.clear()

@router.message(F.text == 'Мои совещания (я организатор)')
async def show_my_meetings(message: types.Message):
    if not await check_user_role(message, UserRole.boss):
        return
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        boss = result.scalar_one_or_none()
        if not boss:
            await message.answer('Ошибка: вы не зарегистрированы.', reply_markup=kb_boss)
            return
        meetings_result = await session.execute(select(Meeting).where(Meeting.creator_id == boss.id))
        meetings = meetings_result.scalars().all()
        if not meetings:
            await message.answer('У вас нет созданных совещаний.', reply_markup=kb_boss)
            return
        for meeting in meetings:
            # Получаем создателя
            creator_result = await session.execute(select(User).where(User.id == meeting.creator_id))
            creator = creator_result.scalar_one_or_none()
            creator_fio = creator.fio if creator else 'Неизвестно'
            text = f'📅 <b>{meeting.topic}</b>\nДата: {meeting.datetime.strftime("%d.%m.%Y %H:%M")}\nДлительность: {meeting.duration} минут\n'
            text += f'Создатель: {creator_fio} \n'
            # Получаем участников, исключая создателя
            participants_result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting.id))
            participants = [p for p in participants_result.scalars().all() if p.user_id != meeting.creator_id]
            if not participants:
                text += 'Нет участников.\n'
            else:
                text += 'Участники:\n'
                for p in participants:
                    user_result = await session.execute(select(User).where(User.id == p.user_id))
                    user = user_result.scalar_one_or_none()
                    fio = user.fio if user else 'Неизвестно'
                    status = {
                        'pending': '⏳ приглашён',
                        'accepted': '✅ подтвердил',
                        'declined': f'❌ отказался ({p.decline_reason or "без причины"})'
                    }.get(p.status, p.status)
                    text += f'— {fio}: {status}\n'
            # Заметки
            notes_result = await session.execute(select(MeetingNote).where(MeetingNote.meeting_id == meeting.id))
            notes = notes_result.scalars().all()
            if notes:
                text += '\nЗаметки:'
                for note in notes:
                    author_result = await session.execute(select(User).where(User.id == note.author_id))
                    author = author_result.scalar_one_or_none()
                    author_name = author.fio if author else 'Неизвестно'
                    local_time = note.created_at + timedelta(hours=8)
                    text += f"\n— {author_name} ({local_time.strftime('%d.%m.%Y %H:%M')}): {note.text}"
            # Inline-кнопки для заметки и напоминания
            from datetime import datetime
            now = datetime.now()
            meeting_started = now >= meeting.datetime
            inline_keyboard = [
                [types.InlineKeyboardButton(text='Добавить заметку', callback_data=f'boss_add_note_{meeting.id}')],
                [types.InlineKeyboardButton(text='Добавить напоминание', callback_data=f'boss_add_reminder_{meeting.id}')]
            ]
            if not meeting_started:
                inline_keyboard.append([types.InlineKeyboardButton(text='Редактировать', callback_data=f'boss_edit_meeting_{meeting.id}')])
                inline_keyboard.append([types.InlineKeyboardButton(text='Удалить', callback_data=f'boss_delete_meeting_{meeting.id}')])
            inline_kb = types.InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
            await message.answer(text, parse_mode='HTML', reply_markup=inline_kb)

@router.callback_query(lambda c: c.data.startswith('boss_add_note_'))
async def boss_add_note_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await check_user_role(callback, UserRole.boss, state):
        return
    meeting_id = int(callback.data.split('_')[-1])
    # Проверка периода совещания
    async with async_session() as session:
        meeting_result = await session.execute(select(Meeting).where(Meeting.id == meeting_id))
        meeting = meeting_result.scalar_one_or_none()
        from datetime import datetime, timedelta
        now = datetime.now()
        if meeting:
            meeting_end = meeting.datetime + timedelta(minutes=meeting.duration)
            if not (meeting.datetime <= now < meeting_end):
                await callback.message.answer('Заметки можно добавлять только в период проведения совещания!')
                await callback.answer()
                return
    await state.update_data(meeting_id=meeting_id)
    await callback.message.answer('Введите текст заметки:')
    await state.set_state(BossMeetingStates.waiting_note)
    await callback.answer()

@router.message(BossMeetingStates.waiting_note)
async def boss_save_meeting_note(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.boss, state):
        return
    data = await state.get_data()
    meeting_id = data.get('meeting_id')
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        from database import MeetingNote
        note = MeetingNote(meeting_id=meeting_id, author_id=user.id, text=message.text)
        session.add(note)
        await session.commit()
        await message.answer('Заметка добавлена!')
    await state.clear()

@router.callback_query(lambda c: c.data.startswith('boss_add_reminder_'))
async def boss_add_reminder_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await check_user_role(callback, UserRole.boss, state):
        return
    meeting_id = int(callback.data.split('_')[-1])
    # Проверка: напоминания можно добавлять только до начала совещания
    async with async_session() as session:
        meeting_result = await session.execute(select(Meeting).where(Meeting.id == meeting_id))
        meeting = meeting_result.scalar_one_or_none()
        from datetime import datetime
        now = datetime.now()
        if meeting and now >= meeting.datetime:
            await callback.message.answer('Нельзя добавить напоминание после начала совещания!')
            await callback.answer()
            return
        # Проверка: начальник должен быть участником и подтвердить участие
        result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        part_result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id, MeetingParticipant.user_id == user.id))
        participant = part_result.scalar_one_or_none()
        # ВРЕМЕННАЯ ОТЛАДКА
        if not participant:
            await callback.message.answer(f'Отладка: начальник не найден среди участников (user_id={user.id})')
        else:
            await callback.message.answer(f'Отладка: статус начальника - {participant.status}')
        if not participant or participant.status != 'accepted':
            await callback.message.answer('Вы можете установить напоминание только после подтверждения участия в совещании.')
            await callback.answer()
            return
    await state.update_data(meeting_id=meeting_id)
    await callback.message.answer('За сколько минут до совещания напомнить? (например, 5, 10, 15, 30, 60)')
    await state.set_state(BossMeetingStates.waiting_reminder)
    await callback.answer()

@router.message(BossMeetingStates.waiting_reminder)
async def boss_save_meeting_reminder(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.boss, state):
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
        from datetime import timedelta
        remind_at = meeting.datetime - timedelta(minutes=minutes)
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        from database import MeetingReminder
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

@router.callback_query(lambda c: c.data.startswith('answer_employee_'))
async def boss_answer_start(callback: types.CallbackQuery, state: FSMContext):
    if not await check_user_role(callback, UserRole.boss, state):
        return
    employee_id = int(callback.data.split('_')[-1])
    await state.update_data(employee_id=employee_id)
    await callback.message.answer('Введите ваш ответ сотруднику:')
    await state.set_state(BossAnswer.waiting_answer)
    await callback.answer()

@router.message(BossAnswer.waiting_answer)
async def boss_send_answer(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.boss, state):
        return
    data = await state.get_data()
    employee_id = data.get('employee_id')
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == employee_id))
        employee = result.scalar_one_or_none()
        if employee:
            try:
                await message.bot.send_message(employee.telegram_id, f'Ответ от начальника:\n{message.text}')
                await message.answer('Ответ отправлен сотруднику.', reply_markup=kb_boss)
            except Exception:
                await message.answer('Ошибка при отправке ответа сотруднику.', reply_markup=kb_boss)
        else:
            await message.answer('Сотрудник не найден.', reply_markup=kb_boss)
    await state.clear()

@router.callback_query(lambda c: c.data.startswith('boss_delete_meeting_'))
async def boss_delete_meeting_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await check_user_role(callback, UserRole.boss, state):
        return
    meeting_id = int(callback.data.split('_')[-1])
    async with async_session() as session:
        meeting_result = await session.execute(select(Meeting).where(Meeting.id == meeting_id))
        meeting = meeting_result.scalar_one_or_none()
        from datetime import datetime
        now = datetime.now()
        if meeting and now >= meeting.datetime:
            await callback.message.answer('Удаление недоступно: совещание уже проводится или завершено.')
            await callback.answer()
            return
    # Запросить подтверждение
    confirm_kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text='Да, удалить', callback_data=f'boss_confirm_delete_{meeting_id}')],
            [types.InlineKeyboardButton(text='Нет, отмена', callback_data='boss_cancel_delete')]
        ]
    )
    await callback.message.answer('Вы уверены, что хотите удалить это совещание? Это действие необратимо.', reply_markup=confirm_kb)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('boss_confirm_delete_'))
async def boss_confirm_delete_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await check_user_role(callback, UserRole.boss, state):
        return
    meeting_id = int(callback.data.split('_')[-1])
    async with async_session() as session:
        # Удаляем участников
        await session.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id).delete(synchronize_session=False))
        # Удаляем напоминания
        await session.execute(select(MeetingReminder).where(MeetingReminder.meeting_id == meeting_id).delete(synchronize_session=False))
        # Удаляем заметки
        await session.execute(select(MeetingNote).where(MeetingNote.meeting_id == meeting_id).delete(synchronize_session=False))
        # Удаляем совещание
        await session.execute(select(Meeting).where(Meeting.id == meeting_id).delete(synchronize_session=False))
        await session.commit()
    await callback.message.answer('Совещание и все связанные данные удалены.')
    await callback.answer()

@router.callback_query(lambda c: c.data == 'boss_cancel_delete')
async def boss_cancel_delete_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer('Удаление совещания отменено.')
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('boss_edit_meeting_'))
async def boss_edit_meeting_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await check_user_role(callback, UserRole.boss, state):
        return
    meeting_id = int(callback.data.split('_')[-1])
    async with async_session() as session:
        meeting_result = await session.execute(select(Meeting).where(Meeting.id == meeting_id))
        meeting = meeting_result.scalar_one_or_none()
        from datetime import datetime
        now = datetime.now()
        if meeting and now >= meeting.datetime:
            await callback.message.answer('Редактирование недоступно: совещание уже проводится или завершено.')
            await callback.answer()
            return
    await state.update_data(meeting_id=meeting_id)
    edit_kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text='Изменить тему', callback_data='boss_edit_topic')],
            [types.InlineKeyboardButton(text='Изменить дату/время', callback_data='boss_edit_datetime')],
            [types.InlineKeyboardButton(text='Изменить участников', callback_data='boss_edit_participants')]
        ]
    )
    await callback.message.answer('Что вы хотите изменить?', reply_markup=edit_kb)
    await state.set_state(BossMeetingStates.waiting_edit_field)
    await callback.answer()

@router.callback_query(lambda c: c.data == 'boss_edit_topic')
async def boss_edit_topic_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer('Введите новую тему совещания:')
    await state.set_state(BossMeetingStates.waiting_new_topic)
    await callback.answer()

@router.message(BossMeetingStates.waiting_new_topic)
async def boss_save_new_topic(message: types.Message, state: FSMContext):
    data = await state.get_data()
    meeting_id = data.get('meeting_id')
    # Если редактируется существующее совещание
    if meeting_id:
        async with async_session() as session:
            result = await session.execute(select(Meeting).where(Meeting.id == meeting_id))
            meeting = result.scalar_one_or_none()
            if not meeting:
                await message.answer('Совещание не найдено.')
                await state.clear()
                return
            meeting.topic = message.text
            await session.commit()
            await message.answer('Тема совещания успешно изменена!')
        await state.clear()
    else:
        # Если это процесс создания нового совещания — обновляем только topic в FSM
        await state.update_data(topic=message.text)
        await message.answer('Тема совещания успешно изменена!')
        # Можно добавить переход к следующему шагу, если требуется
        # Например: await message.answer('Продолжайте создание совещания.')

@router.callback_query(lambda c: c.data == 'boss_edit_datetime')
async def boss_edit_datetime_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer('Введите новую дату и время совещания в формате ДД.ММ.ГГГГ ЧЧ:ММ:')
    await state.set_state(BossMeetingStates.waiting_new_datetime)
    await callback.answer()

@router.message(BossMeetingStates.waiting_new_datetime)
async def boss_save_new_datetime(message: types.Message, state: FSMContext):
    from datetime import datetime
    data = await state.get_data()
    meeting_id = data.get('meeting_id')
    try:
        dt = datetime.strptime(message.text, '%d.%m.%Y %H:%M')
    except ValueError:
        await message.answer('Некорректный формат! Введите дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ')
        return
    if dt < datetime.now():
        await message.answer('Нельзя установить дату в прошлом!')
        return
    async with async_session() as session:
        result = await session.execute(select(Meeting).where(Meeting.id == meeting_id))
        meeting = result.scalar_one_or_none()
        if not meeting:
            await message.answer('Совещание не найдено.')
            await state.clear()
            return
        old_datetime = meeting.datetime
        meeting.datetime = dt
        await session.commit()
        # --- Пересчёт напоминаний ---
        reminders_result = await session.execute(select(MeetingReminder).where(MeetingReminder.meeting_id == meeting_id))
        reminders = reminders_result.scalars().all()
        for reminder in reminders:
            # вычисляем старый интервал (в минутах) между совещанием и напоминанием
            old_delta = (old_datetime - reminder.remind_at).total_seconds() // 60
            # новое время напоминания
            reminder.remind_at = dt - timedelta(minutes=int(old_delta))
        await session.commit()
        # --- Уведомление участникам ---
        # Получаем всех участников
        parts_result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id))
        participants = parts_result.scalars().all()
        # Получаем объект бота
        bot = message.bot
        # Формируем текст уведомления
        notify_text = f'ВНИМАНИЕ! В совещании "{meeting.topic}" изменились дата и/или время.\nНовая дата и время: {meeting.datetime.strftime("%d.%m.%Y %H:%M")}.'
        for part in participants:
            user_result = await session.execute(select(User).where(User.id == part.user_id))
            user = user_result.scalar_one_or_none()
            if user and user.telegram_id:
                try:
                    await bot.send_message(user.telegram_id, notify_text)
                except Exception:
                    pass
        await message.answer('Дата и время совещания успешно изменены! Все участники уведомлены, напоминания обновлены.')
    await state.clear()

@router.callback_query(lambda c: c.data == 'boss_edit_participants')
async def boss_edit_participants_callback(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    meeting_id = data.get('meeting_id')
    async with async_session() as session:
        # Получаем совещание и отдел
        meeting_result = await session.execute(select(Meeting).where(Meeting.id == meeting_id))
        meeting = meeting_result.scalar_one_or_none()
        boss_result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        boss = boss_result.scalar_one_or_none()
        department = boss.department
        # Получаем сотрудников отдела
        result = await session.execute(select(User).where(User.department == department, User.role == UserRole('сотрудник')))
        employees = result.scalars().all()
        # Получаем текущих участников
        parts_result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id))
        participants = [p.user_id for p in parts_result.scalars().all()]
        # Формируем клавиатуру
        kb = get_participants_keyboard(employees, participants, mode='edit')
    await callback.message.answer('Выберите новых участников совещания (нажимайте по очереди, затем "Готово"):', reply_markup=kb)
    await state.update_data(department=department, participants=participants)
    await state.set_state(BossMeetingStates.waiting_edit_participants)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('reject_reason_'))
async def reject_reason_callback(callback: types.CallbackQuery, bot: Bot):
    parts = callback.data.split('_')
    meeting_id = int(parts[2])
    user_id = int(parts[3])
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id, MeetingParticipant.user_id == user_id))
        participant = result.scalar_one_or_none()
        if participant:
            participant.status = 'pending'
            participant.decline_reason = None
            await session.commit()
        try:
            await bot.send_message(user.telegram_id, 'Ваша причина отклонена. Вы снова можете принять или отклонить приглашение.')
        except Exception:
            pass
    await callback.message.edit_text('Причина отклонена, участник снова может принять или отклонить приглашение.')
    await callback.answer() 
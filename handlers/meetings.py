from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from states import CreateMeeting, DeclineMeeting, EmployeeQuestion
from database import async_session, User, Meeting, UserRole, MeetingParticipant
from sqlalchemy.future import select
from keyboards import kb_boss, get_participants_keyboard, kb_employee
from datetime import datetime

router = Router()

@router.message(F.text == 'Создать совещание')
async def create_meeting_start(message: types.Message, state: FSMContext):
    await message.answer('Введите тему совещания:')
    await state.set_state(CreateMeeting.topic)

@router.message(CreateMeeting.topic)
async def create_meeting_topic(message: types.Message, state: FSMContext):
    await state.update_data(topic=message.text)
    await message.answer('Введите дату и время совещания в формате ДД.ММ.ГГГГ ЧЧ:ММ:')
    await state.set_state(CreateMeeting.datetime)

@router.message(CreateMeeting.datetime)
async def create_meeting_datetime(message: types.Message, state: FSMContext):
    try:
        dt = datetime.strptime(message.text, '%d.%m.%Y %H:%M')
    except ValueError:
        await message.answer('Некорректный формат! Введите дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ')
        return
    await state.update_data(datetime=dt)
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
    kb = get_participants_keyboard(employees, [])
    await message.answer('Выберите участников совещания (нажимайте по очереди, затем "Готово"):', reply_markup=kb)
    await state.set_state(CreateMeeting.participants)

@router.callback_query(lambda c: c.data.startswith('add_participant_'))
async def add_participant_callback(callback: types.CallbackQuery, state: FSMContext):
    emp_id = int(callback.data.split('_')[-1])
    data = await state.get_data()
    participants = data.get('participants', [])
    if emp_id not in participants:
        participants.append(emp_id)
        await state.update_data(participants=participants)
    # Получаем сотрудников отдела
    async with async_session() as session:
        result = await session.execute(select(User).where(User.department == data['department'], User.role == UserRole('сотрудник')))
        employees = result.scalars().all()
    kb = get_participants_keyboard(employees, participants)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer('Добавлено!')

@router.callback_query(lambda c: c.data == 'participants_done')
async def participants_done_callback(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get('participants'):
        await callback.answer('Выберите хотя бы одного участника!', show_alert=True)
        return
    await callback.message.answer('Подтвердите создание совещания? (да/нет)')
    await state.set_state(CreateMeeting.confirm)
    await callback.answer()

@router.message(CreateMeeting.confirm)
async def create_meeting_confirm(message: types.Message, state: FSMContext, bot: Bot):
    if message.text.lower() != 'да':
        await message.answer('Создание совещания отменено.', reply_markup=kb_boss)
        await state.clear()
        return
    data = await state.get_data()
    async with async_session() as session:
        # Получаем пользователя (начальника) по telegram_id
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        boss = result.scalar_one_or_none()
        meeting = Meeting(
            topic=data['topic'],
            datetime=data['datetime'],
            creator_id=boss.id
        )
        session.add(meeting)
        await session.commit()
        await session.refresh(meeting)
        # Добавляем участников
        for user_id in data['participants']:
            participant = MeetingParticipant(meeting_id=meeting.id, user_id=user_id, status='pending')
            session.add(participant)
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

@router.callback_query(lambda c: c.data.startswith('meeting_accept_'))
async def meeting_accept_callback(callback: types.CallbackQuery):
    meeting_id = int(callback.data.split('_')[-1])
    user_id = callback.from_user.id
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            await callback.answer('Ошибка!')
            return
        result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id, MeetingParticipant.user_id == user.id))
        participant = result.scalar_one_or_none()
        if participant:
            participant.status = 'accepted'
            await session.commit()
    await callback.message.edit_text('Вы подтвердили участие в совещании.')
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('meeting_decline_'))
async def meeting_decline_callback(callback: types.CallbackQuery, state: FSMContext):
    meeting_id = int(callback.data.split('_')[-1])
    await state.update_data(meeting_id=meeting_id)
    await callback.message.answer('Пожалуйста, введите причину отказа:')
    await state.set_state(DeclineMeeting.waiting_reason)
    await callback.answer()

@router.message(DeclineMeeting.waiting_reason)
async def decline_reason_entered(message: types.Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    meeting_id = data['meeting_id']
    user_id = message.from_user.id
    reason = message.text
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = result.scalar_one_or_none()
        result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id, MeetingParticipant.user_id == user.id))
        participant = result.scalar_one_or_none()
        if participant:
            participant.status = 'declined'
            participant.decline_reason = reason
            await session.commit()
        # Получаем совещание и организатора
        result = await session.execute(select(Meeting).where(Meeting.id == meeting_id))
        meeting = result.scalar_one_or_none()
        result = await session.execute(select(User).where(User.telegram_id == meeting.creator_id))
        boss = result.scalar_one_or_none()
        if boss:
            kb = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text='Принять причину', callback_data=f'accept_reason_{meeting_id}_{user.id}')],
                    [types.InlineKeyboardButton(text='Отклонить причину', callback_data=f'reject_reason_{meeting_id}_{user.id}')]
                ]
            )
            try:
                await bot.send_message(boss.telegram_id, f'Пользователь {user.fio} отклонил участие в совещании "{meeting.topic}".\nПричина: {reason}', reply_markup=kb)
            except Exception:
                pass
    await message.answer('Ваша причина отправлена организатору. Ожидайте решения.')
    await state.clear()

@router.callback_query(lambda c: c.data.startswith('accept_reason_'))
async def accept_reason_callback(callback: types.CallbackQuery, bot: Bot):
    parts = callback.data.split('_')
    meeting_id = int(parts[2])
    user_id = int(parts[3])
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id, MeetingParticipant.user_id == user_id))
        participant = result.scalar_one_or_none()
        if participant:
            await session.delete(participant)
            await session.commit()
        try:
            await bot.send_message(user.telegram_id, 'Ваша причина принята, участие отклонено.')
        except Exception:
            pass
    await callback.message.edit_text('Причина принята, участник удалён из совещания.')
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('reject_reason_'))
async def reject_reason_callback(callback: types.CallbackQuery, bot: Bot):
    parts = callback.data.split('_')
    meeting_id = int(parts[2])
    user_id = int(parts[3])
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            try:
                await bot.send_message(user.telegram_id, 'Ваша причина отклонена. Вы остаетесь участником совещания.')
            except Exception:
                pass
    await callback.message.edit_text('Причина отклонена.')
    await callback.answer()

@router.message(F.text == 'Ответить на вопросы')
async def answer_questions(message: types.Message):
    await message.answer('Функция ответа на вопросы в разработке.')

@router.message(F.text == 'Мои совещания')
async def show_my_meetings(message: types.Message):
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
            text = f'📅 <b>{meeting.topic}</b>\nДата: {meeting.datetime.strftime("%d.%m.%Y %H:%M")}\n'
            # Получаем участников
            participants_result = await session.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting.id))
            participants = participants_result.scalars().all()
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
            await message.answer(text, parse_mode='HTML', reply_markup=kb_boss)

@router.message(F.text == 'Мои приглашения')
async def show_my_invitations(message: types.Message):
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
                await message.answer(f'Приглашение: {meeting.topic}\nДата: {meeting.datetime.strftime("%d.%m.%Y %H:%M")}\nДлительность: {meeting.duration} минут', reply_markup=kb_employee)

@router.message(F.text == 'Мои совещания')
async def show_my_accepted_meetings(message: types.Message):
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
    await message.answer('Введите ваш вопрос начальнику:')
    await state.set_state(EmployeeQuestion.waiting_question)

@router.message(EmployeeQuestion.waiting_question)
async def send_question_to_boss(message: types.Message, state: FSMContext):
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
            await message.bot.send_message(boss.telegram_id, f'Вопрос от сотрудника {user.fio}:\n{message.text}')
            await message.answer('Ваш вопрос отправлен начальнику.', reply_markup=kb_employee)
        except Exception:
            await message.answer('Ошибка при отправке вопроса начальнику.', reply_markup=kb_employee)
        await state.clear() 
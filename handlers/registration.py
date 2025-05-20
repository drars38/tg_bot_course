from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from states import Registration
from keyboards import kb_departments, kb_roles,kb_employee, kb_admin, kb_boss, DEPARTMENTS
from database import async_session, User, UserRole
from sqlalchemy.future import select
from aiogram import Bot

router = Router()

@router.message(Command('start'))
async def cmd_start(message: types.Message, state: FSMContext):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        if user:
            role = user.role if isinstance(user.role, UserRole) else UserRole(user.role)
            if role == UserRole.admin:
                await message.answer(f'Вы уже зарегистрированы как {role.value}.', reply_markup=kb_admin)
            elif role == UserRole.boss:
                await message.answer(f'Вы уже зарегистрированы как {role.value}.', reply_markup=kb_boss)
            elif role == UserRole.employee:
                await message.answer(f'Вы уже зарегистрированы как {role.value}.', reply_markup=kb_employee)
            else:
                await message.answer(f'Вы уже зарегистрированы как {role.value}.', reply_markup=types.ReplyKeyboardRemove())
            return
        await message.answer('Добро пожаловать! Для регистрации отправьте свою контакт-карточку Telegram (кнопка ниже):',
                             reply_markup=types.ReplyKeyboardMarkup(
                                 keyboard=[[types.KeyboardButton(text='Отправить контакт', request_contact=True)]],
                                 resize_keyboard=True
                             ))
        await state.set_state(Registration.phone)

@router.message(Registration.phone)
async def reg_phone(message: types.Message, state: FSMContext):
    if not message.contact or not message.contact.phone_number:
        await message.answer('Пожалуйста, используйте кнопку для отправки своего контакта!')
        return
    await state.update_data(phone=message.contact.phone_number, telegram_id=message.contact.user_id)
    await message.answer('Введите ваше ФИО:', reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Registration.fio)

@router.message(Registration.fio)
async def reg_fio(message: types.Message, state: FSMContext):
    await state.update_data(fio=message.text)
    await message.answer('Выберите ваш отдел:', reply_markup=kb_departments)
    await state.set_state(Registration.department)

@router.message(Registration.department)
async def reg_department(message: types.Message, state: FSMContext):
    if message.text not in DEPARTMENTS:
        await message.answer('Пожалуйста, выберите отдел из списка.')
        return
    await state.update_data(department=message.text)
    await message.answer('Введите вашу должность:')
    await state.set_state(Registration.position)

@router.message(Registration.position)
async def reg_position(message: types.Message, state: FSMContext, bot: Bot):
    await state.update_data(position=message.text)
    data = await state.get_data()
    fio = data['fio']
    department = data['department']
    phone = data['phone']
    telegram_id = data['telegram_id']
    position = data['position']
    # Проверяем, есть ли уже администратор
    async with async_session() as session:
        result = await session.execute(select(User).where(User.role == UserRole.admin))
        admin_exists = result.scalar_one_or_none() is not None
    role = UserRole.admin if not admin_exists else UserRole.employee
    user = User(telegram_id=telegram_id, fio=fio, department=department, phone=phone, position=position, role=role)
    async with async_session() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
    await state.clear()
    await message.answer('Регистрация завершена! Ожидайте, пока администратор назначит вам роль.')
    # Уведомляем всех админов
    async with async_session() as session:
        result = await session.execute(select(User).where(User.role == UserRole.admin))
        admins = result.scalars().all()
    text = f'Новый пользователь зарегистрировался:\n\nФИО: {fio}\nОтдел: {department}\nДолжность: {position}\nТелефон: {phone}\nTelegram ID: {telegram_id}'
    inline_kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text='Назначить администратором', callback_data=f'setrole_{user.id}_{UserRole.admin.value}')],
            [types.InlineKeyboardButton(text='Назначить начальником', callback_data=f'setrole_{user.id}_{UserRole.boss.value}')],
            [types.InlineKeyboardButton(text='Назначить сотрудником', callback_data=f'setrole_{user.id}_{UserRole.employee.value}')]
        ]
    )
    for admin in admins:
        try:
            await bot.send_message(admin.telegram_id, text, reply_markup=inline_kb)
        except Exception:
            pass
    role = user.role if isinstance(user.role, UserRole) else UserRole(user.role)
    if role == UserRole.admin:
        await message.answer(f'Вы уже зарегистрированы как {role.value}.', reply_markup=kb_admin)
    elif role == UserRole.boss:
        await message.answer(f'Вы уже зарегистрированы как {role.value}.', reply_markup=kb_boss)
    elif role == UserRole.employee:
        await message.answer(f'Вы уже зарегистрированы как {role.value}.', reply_markup=kb_employee)
    else:
        await message.answer(f'Вы уже зарегистрированы как {role.value}.', reply_markup=types.ReplyKeyboardRemove())


from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from keyboards import kb_admin,kb_boss, kb_edit_user, kb_departments, kb_roles, kb_edit_user_inline, get_departments_keyboard, get_roles_keyboard, get_users_keyboard, kb_employee, kb_back
from states import AddUser, EditUser, DeleteUserFSM
from services.user_service import add_user_to_db, get_users_by_dep_and_role, update_user_in_db, change_user_role, check_user_role
from keyboards import DEPARTMENTS
from aiogram.filters import Command
from database import async_session, User, UserRole
from sqlalchemy.future import select
from aiogram import Bot
from aiogram.fsm.storage.base import StorageKey

router = Router()

@router.message(F.text == 'Добавить пользователя')
async def admin_add_user(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    await message.answer('Введите ФИО нового пользователя:', reply_markup=kb_back)
    await state.set_state(AddUser.fio)

@router.message(AddUser.fio)
async def add_user_fio(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    if message.text == 'Назад':
        await message.answer('Возврат к меню администратора.', reply_markup=kb_admin)
        await state.clear()
        return
    await state.update_data(fio=message.text)
    await message.answer('Выберите отдел пользователя:', reply_markup=kb_departments)
    await state.set_state(AddUser.department)

@router.message(AddUser.department)
async def add_user_department(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    if message.text == 'Назад':
        await message.answer('Возврат к меню администратора.', reply_markup=kb_admin)
        await state.clear()
        return
    if message.text not in DEPARTMENTS:
        await message.answer('Пожалуйста, выберите отдел из списка.')
        return
    await state.update_data(department=message.text)
    await message.answer('Выберите роль пользователя:', reply_markup=kb_roles)
    await state.set_state(AddUser.role)

@router.message(AddUser.role)
async def add_user_role(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    if message.text == 'Назад':
        await message.answer('Возврат к меню администратора.', reply_markup=kb_admin)
        await state.clear()
        return
    if message.text not in ['администратор', 'начальник', 'сотрудник']:
        await message.answer('Пожалуйста, выберите роль с клавиатуры.')
        return
    await state.update_data(role=UserRole(message.text))
    await message.answer('Введите должность пользователя:')
    await state.set_state(AddUser.position)

@router.message(AddUser.position)
async def add_user_position(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    if message.text == 'Назад':
        await message.answer('Возврат к меню администратора.', reply_markup=kb_admin)
        await state.clear()
        return
    await state.update_data(position=message.text)
    await message.answer('Введите номер телефона пользователя:')
    await state.set_state(AddUser.phone)

@router.message(AddUser.phone)
async def add_user_phone(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    if message.text == 'Назад':
        await message.answer('Возврат к меню администратора.', reply_markup=kb_admin)
        await state.clear()
        return
    await state.update_data(phone=message.text)
    data = await state.get_data()
    user = await add_user_to_db(
        telegram_id=None,  # пока не знаем telegram_id
        fio=data['fio'],
        department=data['department'],
        role=data['role'],
        position=data['position'],
        phone=data['phone']
    )
    await state.clear()
    await message.answer(f'Пользователь {data["fio"]} успешно добавлен!', reply_markup=kb_admin)
    # Здесь можно реализовать отправку сообщения пользователю, если он уже запускал бота

@router.message(F.text == 'Редактировать пользователя')
async def admin_edit_user(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    await message.answer('Выберите отдел пользователя для редактирования:', reply_markup=get_departments_keyboard())
    await state.set_state(EditUser.select_department)

@router.message(EditUser.select_department)
async def edit_user_select_department(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    if message.text == 'Назад':
        await message.answer('Возврат к меню администратора.', reply_markup=kb_admin)
        await state.clear()
        return
    if message.text not in DEPARTMENTS:
        await message.answer('Пожалуйста, выберите отдел из списка.')
        return
    await state.update_data(department=message.text)
    await message.answer('Выберите роль пользователя:', reply_markup=get_roles_keyboard())
    await state.set_state(EditUser.select_role)

@router.message(EditUser.select_role)
async def edit_user_select_role(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    if message.text not in ['администратор', 'начальник', 'сотрудник']:
        await message.answer('Пожалуйста, выберите роль с клавиатуры.')
        return
    await state.update_data(role=UserRole(message.text))
    data = await state.get_data()
    users = await get_users_by_dep_and_role(data['department'], data['role'])
    if not users:
        await message.answer('Пользователи не найдены. Попробуйте другой отдел или роль.', reply_markup=kb_admin)
        await state.clear()
        return
    kb_users = types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text=f'{u.fio} (id:{u.id})')] for u in users],
        resize_keyboard=True
    )
    await message.answer('Выберите пользователя для редактирования:', reply_markup=kb_users)
    await state.set_state(EditUser.select_user)

@router.message(EditUser.select_user)
async def edit_user_select_user(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    import re
    match = re.search(r'id:(\d+)', message.text)
    if not match:
        await message.answer('Пожалуйста, выберите пользователя из списка.')
        return
    user_id = int(match.group(1))
    await state.update_data(user_id=user_id)
    users = await state.get_data()
    users_list = await get_users_by_dep_and_role(users['department'], users['role'])
    user = next((u for u in users_list if u.id == user_id), None)
    if not user:
        await message.answer('Пользователь не найден.')
        return
    text = f"ФИО: {user.fio}\nРоль: {user.role.value}\nОтдел: {user.department}\nДолжность: {user.position or '-'}\nТелефон: {user.phone or '-'}"
    await message.answer(text, reply_markup=kb_edit_user_inline)
    await state.set_state(EditUser.edit_field)

@router.callback_query(lambda c: c.data in ['edit_fio', 'edit_role', 'edit_department', 'edit_position'])
async def edit_user_inline_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await check_user_role(callback, UserRole.admin, state):
        return
    data = await state.get_data()
    await state.update_data(user_id=data.get('user_id'))
    if callback.data == 'edit_fio':
        await callback.message.answer('Введите новое ФИО:')
        await state.set_state(EditUser.edit_fio)
    elif callback.data == 'edit_role':
        await callback.message.answer('Выберите новую роль:', reply_markup=kb_roles)
        await state.set_state(EditUser.edit_role)
    elif callback.data == 'edit_department':
        await callback.message.answer('Выберите новый отдел:', reply_markup=kb_departments)
        await state.set_state(EditUser.edit_department)
    elif callback.data == 'edit_position':
        await callback.message.answer('Введите новую должность:')
        await state.set_state(EditUser.edit_position)
    await callback.answer()

@router.message(EditUser.edit_fio)
async def edit_user_fio(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    data = await state.get_data()
    await update_user_in_db(data['user_id'], fio=message.text)
    # Получаем обновлённые данные пользователя
    users_list = await get_users_by_dep_and_role(data['department'], data['role'])
    user = next((u for u in users_list if u.id == data['user_id']), None)
    text = f"ФИО: {user.fio}\nРоль: {user.role.value}\nОтдел: {user.department}\nДолжность: {user.position or '-'}\nТелефон: {user.phone or '-'}"
    await message.answer('ФИО успешно обновлено!\n\n' + text, reply_markup=kb_edit_user_inline)
    await state.set_state(EditUser.edit_field)

@router.message(EditUser.edit_role)
async def edit_user_role(message: types.Message, state: FSMContext, bot: Bot):
    if not await check_user_role(message, UserRole.admin, state):
        return
    if message.text not in ['администратор', 'начальник', 'сотрудник']:
        await message.answer('Пожалуйста, выберите роль с клавиатуры.')
        return
    data = await state.get_data()
    role_value = UserRole(message.text)
    await update_user_in_db(data['user_id'], role=role_value)
    users_list = await get_users_by_dep_and_role(data['department'], role_value)
    user = next((u for u in users_list if u.id == data['user_id']), None)
    text = f"ФИО: {user.fio}\nРоль: {user.role.value if hasattr(user.role, 'value') else user.role}\nОтдел: {user.department}\nДолжность: {user.position or '-'}\nТелефон: {user.phone or '-'}"
    await message.answer('Роль успешно обновлена!\n\n' + text, reply_markup=kb_edit_user_inline)
    await state.update_data(role=role_value)
    await state.set_state(EditUser.edit_field)

    # Логирование для диагностики
    print(f'[DEBUG] Начинаю сброс состояния FSM для пользователя {user.fio} ({user.telegram_id})')
    try:
        if user and user.telegram_id:
            bot_id = (await bot.get_me()).id
            key = StorageKey(bot_id=bot_id, chat_id=user.telegram_id, user_id=user.telegram_id)
            await state.storage.set_state(key, None)
            await state.storage.set_data(key, {})
            print(f'[DEBUG] Состояние FSM сброшено для пользователя {user.fio} ({user.telegram_id})')
            if user.role == UserRole.admin:
                kb = kb_admin
            elif user.role == UserRole.boss:
                kb = kb_boss
            elif user.role == UserRole.employee:
                kb = kb_employee
            else:
                kb = types.ReplyKeyboardRemove()
            print(f'[DEBUG] Отправляю сообщение о смене роли пользователю {user.fio} ({user.telegram_id})')
            await message.bot.send_message(user.telegram_id, f'Ваша роль изменена: {user.role.value}', reply_markup=kb)
            print(f'[DEBUG] Сообщение о смене роли отправлено пользователю {user.fio} ({user.telegram_id})')
            await message.bot.send_message(user.telegram_id, 'Меню доступно ниже 👇', reply_markup=kb)
            print(f'[DEBUG] Сообщение с меню отправлено пользователю {user.fio} ({user.telegram_id})')
    except Exception as e:
        print(f'[ERROR] Ошибка при отправке уведомления пользователю {user.fio} ({user.telegram_id}): {e}')

@router.message(EditUser.edit_department)
async def edit_user_department(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    if message.text not in DEPARTMENTS:
        await message.answer('Пожалуйста, выберите отдел из списка.')
        return
    data = await state.get_data()
    await update_user_in_db(data['user_id'], department=message.text)
    users_list = await get_users_by_dep_and_role(message.text, data['role'])
    user = next((u for u in users_list if u.id == data['user_id']), None)
    text = f"ФИО: {user.fio}\nРоль: {user.role.value}\nОтдел: {user.department}\nДолжность: {user.position or '-'}\nТелефон: {user.phone or '-'}"
    await message.answer('Отдел успешно обновлён!\n\n' + text, reply_markup=kb_edit_user_inline)
    await state.update_data(department=message.text)
    await state.set_state(EditUser.edit_field)

@router.message(EditUser.edit_position)
async def edit_user_position(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    data = await state.get_data()
    await update_user_in_db(data['user_id'], position=message.text)
    users_list = await get_users_by_dep_and_role(data['department'], data['role'])
    user = next((u for u in users_list if u.id == data['user_id']), None)
    text = f"ФИО: {user.fio}\nРоль: {user.role.value}\nОтдел: {user.department}\nДолжность: {user.position or '-'}\nТелефон: {user.phone or '-'}"
    await message.answer('Должность успешно обновлена!\n\n' + text, reply_markup=kb_edit_user_inline)
    await state.set_state(EditUser.edit_field)

@router.message(F.text == 'Удалить пользователя')
async def admin_delete_user(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    await message.answer('Выберите отдел пользователя для удаления:', reply_markup=kb_departments)
    await state.set_state(DeleteUserFSM.select_department)

@router.message(DeleteUserFSM.select_department)
async def delete_user_select_department(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    if message.text not in DEPARTMENTS:
        await message.answer('Пожалуйста, выберите отдел из списка.')
        return
    await state.update_data(department=message.text)
    await message.answer('Выберите роль пользователя:', reply_markup=kb_roles)
    await state.set_state(DeleteUserFSM.select_role)

@router.message(DeleteUserFSM.select_role)
async def delete_user_select_role(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    if message.text not in ['администратор', 'начальник', 'сотрудник']:
        await message.answer('Пожалуйста, выберите роль с клавиатуры.')
        return
    await state.update_data(role=UserRole(message.text))
    data = await state.get_data()
    users = await get_users_by_dep_and_role(data['department'], data['role'])
    if not users:
        await message.answer('Пользователи не найдены. Попробуйте другой отдел или роль.', reply_markup=kb_admin)
        await state.clear()
        return
    kb_users = types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text=f'{u.fio} (id:{u.id})')] for u in users],
        resize_keyboard=True
    )
    await message.answer('Выберите пользователя для удаления:', reply_markup=kb_users)
    await state.set_state(DeleteUserFSM.select_user)

@router.message(DeleteUserFSM.select_user)
async def delete_user_select_user(message: types.Message, state: FSMContext):
    if not await check_user_role(message, UserRole.admin, state):
        return
    import re
    match = re.search(r'id:(\d+)', message.text)
    if not match:
        await message.answer('Пожалуйста, выберите пользователя из списка.')
        return
    user_id = int(match.group(1))
    await state.update_data(user_id=user_id)
    data = await state.get_data()
    users_list = await get_users_by_dep_and_role(data['department'], data['role'])
    user = next((u for u in users_list if u.id == user_id), None)
    if not user:
        await message.answer('Пользователь не найден.')
        return
    text = f"ФИО: {user.fio}\nРоль: {user.role.value}\nОтдел: {user.department}\nДолжность: {user.position or '-'}\nТелефон: {user.phone or '-'}"
    inline_kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text='Удалить', callback_data='delete_user_confirm')],
            [types.InlineKeyboardButton(text='Отмена', callback_data='delete_user_cancel')]
        ]
    )
    await message.answer('Подтвердите удаление пользователя:\n\n' + text, reply_markup=inline_kb)
    await state.set_state(DeleteUserFSM.confirm)

@router.callback_query(lambda c: c.data == 'delete_user_confirm')
async def delete_user_confirm(callback: types.CallbackQuery, state: FSMContext):
    if not await check_user_role(callback, UserRole.admin, state):
        return
    data = await state.get_data()
    user_id = data.get('user_id')
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            await session.delete(user)
            await session.commit()
    await callback.message.answer('Пользователь успешно удалён.', reply_markup=kb_admin)
    await state.clear()
    await callback.answer()

@router.callback_query(lambda c: c.data == 'delete_user_cancel')
async def delete_user_cancel(callback: types.CallbackQuery, state: FSMContext):
    if not await check_user_role(callback, UserRole.admin, state):
        return
    await callback.message.answer('Удаление отменено.', reply_markup=kb_admin)
    await state.clear()
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('setrole_'))
async def set_user_role_callback(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
    if not await check_user_role(callback, UserRole.admin, state):
        return
    import re
    from keyboards import kb_admin, kb_boss, kb_employee
    match = re.match(r'setrole_(\d+)_(.+)', callback.data)
    if not match:
        await callback.answer('Ошибка данных!', show_alert=True)
        return
    user_id, role_value = int(match.group(1)), match.group(2)
    role_value = UserRole(role_value)
    success = await change_user_role(user_id, role_value)
    if not success:
        await callback.answer('Нельзя сменить роль последнего администратора!', show_alert=True)
        return
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
    # Логирование для диагностики
    print(f'[DEBUG] Начинаю сброс состояния FSM для пользователя {user.fio} ({user.telegram_id})')
    try:
        if user and user.telegram_id:
            bot_id = (await bot.get_me()).id
            key = StorageKey(bot_id=bot_id, chat_id=user.telegram_id, user_id=user.telegram_id)
            await state.storage.set_state(key, None)
            await state.storage.set_data(key, {})
            print(f'[DEBUG] Состояние FSM сброшено для пользователя {user.fio} ({user.telegram_id})')
            if user.role == UserRole.admin:
                kb = kb_admin
            elif user.role == UserRole.boss:
                kb = kb_boss
            elif user.role == UserRole.employee:
                kb = kb_employee
        else:
            kb = types.ReplyKeyboardRemove()
            print(f'[DEBUG] Отправляю сообщение о смене роли пользователю {user.fio} ({user.telegram_id})')
            await bot.send_message(user.telegram_id, f'Ваша роль назначена: {user.role.value}', reply_markup=kb)
            print(f'[DEBUG] Сообщение о смене роли отправлено пользователю {user.fio} ({user.telegram_id})')
            await bot.send_message(user.telegram_id, 'Меню доступно ниже 👇', reply_markup=kb)
            print(f'[DEBUG] Сообщение с меню отправлено пользователю {user.fio} ({user.telegram_id})')
    except Exception as e:
        print(f'[ERROR] Ошибка при отправке уведомления пользователю {user.fio} ({user.telegram_id}): {e}')
    await callback.message.answer(f'Роль пользователя {user.fio} успешно назначена: {user.role.value}', reply_markup=kb_admin)
    await callback.answer('Роль назначена!')

@router.callback_query(lambda c: c.data == 'edit_done')
async def edit_user_done(callback: types.CallbackQuery, state: FSMContext):
    if not await check_user_role(callback, UserRole.admin, state):
        return
    await callback.message.answer('Редактирование пользователя завершено.', reply_markup=kb_admin)
    await state.clear()
    await callback.answer()

@router.callback_query(lambda c: c.data == 'edit_back')
async def edit_user_back(callback: types.CallbackQuery, state: FSMContext):
    if not await check_user_role(callback, UserRole.admin, state):
        return
    await callback.message.answer('Возврат к меню администратора.', reply_markup=kb_admin)
    await state.clear()
    await callback.answer() 
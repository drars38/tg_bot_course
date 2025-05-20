from database import async_session, User, UserRole
from sqlalchemy.future import select
from keyboards import kb_admin, kb_boss, kb_employee
from aiogram.types import Message, CallbackQuery

async def add_user_to_db(telegram_id, fio, department, role, position, phone):
    async with async_session() as session:
        # Приводим роль к Enum, если это строка
        if isinstance(role, str):
            role = UserRole(role)
        user = User(
            telegram_id=telegram_id,
            fio=fio,
            department=department,
            role=role,
            position=position,
            phone=phone
        )
        session.add(user)
        await session.commit()
        return user

async def get_users_by_dep_and_role(department, role):
    async with async_session() as session:
        # Приводим роль к Enum, если это строка
        if isinstance(role, str):
            role = UserRole(role)
        result = await session.execute(select(User).where(User.department == department, User.role == role))
        return result.scalars().all()

async def update_user_in_db(user_id, **kwargs):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return None
        for key, value in kwargs.items():
            if key == 'role':
                if isinstance(value, str):
                    value = UserRole(value)
                setattr(user, key, value)
            elif key != 'role':
                setattr(user, key, value)
        await session.commit()
        return user

async def change_user_role(user_id, new_role):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return False
        # Приводим роль к Enum, если это строка
        if isinstance(new_role, str):
            new_role = UserRole(new_role)
        if user.role == UserRole.admin and new_role != UserRole.admin:
            # Проверяем, есть ли другие админы
            result = await session.execute(
                select(User).where(User.role == UserRole.admin, User.id != user_id)
            )
            other_admin = result.scalar_one_or_none()
            if not other_admin:
                return False  # Запретить смену роли последнего админа
        user.role = new_role
        await session.commit()
        return True

async def check_user_role(event, required_role, state=None):
    """
    Проверяет, соответствует ли роль пользователя требуемой.
    Поддерживает как message, так и callback.
    Если нет — сбрасывает FSM (если передан state), отправляет ошибку и возвращает False.
    Если да — возвращает True.
    """
    # Универсально определяем telegram_id
    telegram_id = None
    if hasattr(event, 'from_user'):
        telegram_id = event.from_user.id
    elif hasattr(event, 'message') and hasattr(event.message, 'from_user'):
        telegram_id = event.message.from_user.id
    else:
        print('[DEBUG] Не удалось определить telegram_id для проверки роли')
        return False
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        print(f"[DEBUG] check_user_role: user={user}, user_role={getattr(user, 'role', None)}, required_role={required_role}")
        if not user or user.role != required_role:
            if state:
                await state.clear()
            # Определяем клавиатуру по роли пользователя
            kb = None
            if user:
                if user.role == UserRole.admin:
                    kb = kb_admin
                elif user.role == UserRole.boss:
                    kb = kb_boss
                elif user.role == UserRole.employee:
                    kb = kb_employee
            await event.answer('У вас нет доступа к этому действию. Пожалуйста, выберите действие из своего меню.', reply_markup=kb)
            return False
        return True 
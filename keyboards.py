from aiogram import types

DEPARTMENTS = ['Отдел продаж', 'Бухгалтерия', 'ИТ', 'Кадры']

# Клавиатура выбора отдела
kb_departments = types.ReplyKeyboardMarkup(
    keyboard=[[types.KeyboardButton(text=dep)] for dep in DEPARTMENTS],
    resize_keyboard=True
)

# Клавиатура выбора роли
kb_roles = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text='администратор')],
        [types.KeyboardButton(text='начальник')],
        [types.KeyboardButton(text='сотрудник')]
    ],
    resize_keyboard=True
)

# Клавиатура администратора
kb_admin = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text='Добавить пользователя')],
        [types.KeyboardButton(text='Редактировать пользователя')],
        [types.KeyboardButton(text='Удалить пользователя')]
    ],
    resize_keyboard=True
)

# Клавиатура начальника
kb_boss = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text='Создать совещание')],
        [types.KeyboardButton(text='Мои совещания (я организатор)')],
        [types.KeyboardButton(text='Ответить на вопросы')]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

# Клавиатура для редактирования пользователя
kb_edit_user = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text='ФИО')],
        [types.KeyboardButton(text='Роль')],
        [types.KeyboardButton(text='Отдел')],
        [types.KeyboardButton(text='Должность')]
    ],
    resize_keyboard=True
)

# Inline клавиатура для редактирования пользователя
kb_edit_user_inline = types.InlineKeyboardMarkup(
    inline_keyboard=[
        [types.InlineKeyboardButton(text='ФИО', callback_data='edit_fio')],
        [types.InlineKeyboardButton(text='Роль', callback_data='edit_role')],
        [types.InlineKeyboardButton(text='Отдел', callback_data='edit_department')],
        [types.InlineKeyboardButton(text='Должность', callback_data='edit_position')],
        [types.InlineKeyboardButton(text='Готово', callback_data='edit_done')],
        [types.InlineKeyboardButton(text='Назад', callback_data='edit_back')]
    ]
)

# Клавиатура с кнопкой 'Назад'
kb_back = types.ReplyKeyboardMarkup(
    keyboard=[[types.KeyboardButton(text='Назад')]],
    resize_keyboard=True
)

# Клавиатура сотрудника
kb_employee = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text='Мои приглашения')],
        [types.KeyboardButton(text='Мои совещания (я участник)')],
        [types.KeyboardButton(text='Задать вопрос начальнику')]
    ],
    resize_keyboard=True
)

def get_departments_keyboard():
    kb = [[types.KeyboardButton(text=dep)] for dep in DEPARTMENTS]
    kb.append([types.KeyboardButton(text='Назад')])
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_roles_keyboard():
    kb = [
        [types.KeyboardButton(text='администратор')],
        [types.KeyboardButton(text='начальник')],
        [types.KeyboardButton(text='сотрудник')],
        [types.KeyboardButton(text='Назад')]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_users_keyboard(users):
    kb = [[types.KeyboardButton(text=f'{u.fio} (id:{u.id})')] for u in users]
    kb.append([types.KeyboardButton(text='Назад')])
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True) 

def get_participants_keyboard(employees, selected_ids, mode='create'):
    kb = []
    for emp in employees:
        mark = ' ✅' if emp.id in selected_ids else ''
        kb.append([types.InlineKeyboardButton(text=emp.fio + mark, callback_data=f'add_participant_{emp.id}')])
    done_callback = 'participants_done_create' if mode == 'create' else 'participants_done_edit'
    kb.append([types.InlineKeyboardButton(text='Готово', callback_data=done_callback)])
    return types.InlineKeyboardMarkup(inline_keyboard=kb) 
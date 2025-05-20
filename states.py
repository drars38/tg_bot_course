from aiogram.fsm.state import StatesGroup, State
class DeleteUserFSM(StatesGroup):
    select_department = State()
    select_role = State()
    select_user = State()
    confirm = State()
    
class Registration(StatesGroup):
    phone = State()
    fio = State()
    department = State()
    position = State()

class AddUser(StatesGroup):
    fio = State()
    department = State()
    role = State()
    position = State()
    phone = State()

class EditUser(StatesGroup):
    select_department = State()
    select_role = State()
    select_user = State()
    show_user = State()
    edit_field = State()
    edit_fio = State()
    edit_role = State()
    edit_department = State()
    edit_position = State()

class CreateMeeting(StatesGroup):
    topic = State()
    datetime = State()
    duration = State()
    participants = State()
    confirm = State()

class DeclineMeeting(StatesGroup):
    waiting_reason = State()

class EmployeeQuestion(StatesGroup):
    waiting_question = State()

class BossAnswer(StatesGroup):
    waiting_answer = State()

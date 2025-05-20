from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text, Boolean
import enum
from config import DB_URL
from datetime import datetime

Base = declarative_base()
engine = create_async_engine(DB_URL, echo=True)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class UserRole(enum.Enum):
    admin = 'администратор'
    boss = 'начальник'
    employee = 'сотрудник'

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=True)
    fio = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=True)
    department = Column(String)
    position = Column(String)
    phone = Column(String)

class Meeting(Base):
    __tablename__ = 'meetings'
    id = Column(Integer, primary_key=True)
    topic = Column(String, nullable=False)
    description = Column(Text)
    datetime = Column(DateTime, nullable=False)
    duration = Column(Integer, nullable=False, default=60)  # длительность в минутах
    creator_id = Column(Integer, ForeignKey('users.id'))
    creator = relationship('User')

class MeetingParticipant(Base):
    __tablename__ = 'meeting_participants'
    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey('meetings.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    status = Column(String, default='pending')  # pending, accepted, declined
    decline_reason = Column(String)
    meeting = relationship('Meeting', backref='participants')
    user = relationship('User')

class MeetingNote(Base):
    __tablename__ = 'meeting_notes'
    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey('meetings.id'))
    author_id = Column(Integer, ForeignKey('users.id'))
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    meeting = relationship('Meeting', backref='notes')
    author = relationship('User')

class MeetingReminder(Base):
    __tablename__ = 'meeting_reminders'
    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey('meetings.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    remind_at = Column(DateTime, nullable=False)
    sent = Column(Boolean, default=False)
    meeting = relationship('Meeting', backref='reminders')
    user = relationship('User')

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all) 
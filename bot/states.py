from aiogram.fsm.state import State, StatesGroup

class SetupStates(StatesGroup):
    waiting_for_channel = State()
    waiting_for_signature = State()

class SyncStates(StatesGroup):
    waiting_for_target = State()
    waiting_for_interval = State()

class QuickGrabStates(StatesGroup):
    waiting_for_link = State()

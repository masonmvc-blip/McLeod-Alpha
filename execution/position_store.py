from engine.memory import get_memory

def save_position(position):
    get_memory().save_position(position)


def load_position(Position):
    return get_memory().load_position(Position)


def clear_position():
    get_memory().clear_position()
from engine.memory import get_memory

def log_signal(price, regime, call_score, put_score, feature_payload=None):
    get_memory().record_signal(price, regime, call_score, put_score, feature_payload)
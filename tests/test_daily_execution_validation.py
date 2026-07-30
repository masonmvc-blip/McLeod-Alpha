from scripts import daily_execution_validation as validation


def test_execution_validation_defaults_to_local_cockpit():
    assert validation.BASE_URL == "http://127.0.0.1:5001"
    assert validation.EASTERN_NOW.tzinfo is not None

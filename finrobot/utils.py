from datetime import date


def get_current_date():
    return date.today().strftime("%Y-%m-%d")
from datetime import date


def get_curday():
    return date.today().strftime("%Y-%m-%d")
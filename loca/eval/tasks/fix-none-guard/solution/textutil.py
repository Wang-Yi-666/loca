"""Text helpers."""


def initials(name):
    """Initials of a full name, e.g. "Ada Lovelace" -> "AL".

    A blank or missing name yields "".
    """
    if not name:
        return ""
    parts = name.split()
    return "".join(part[0] for part in parts).upper()

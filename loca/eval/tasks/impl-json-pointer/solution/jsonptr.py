"""RFC 6901 JSON Pointer resolution."""


def _decode(token):
    """Unescape a reference token. Order matters: ~1 before ~0."""
    return token.replace("~1", "/").replace("~0", "~")


def resolve(document, pointer):
    """Resolve a JSON Pointer against a parsed JSON document."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError(f"invalid pointer {pointer!r}")
    current = document
    for token in pointer[1:].split("/"):
        key = _decode(token)
        if isinstance(current, dict):
            if key not in current:
                raise KeyError(key)
            current = current[key]
        elif isinstance(current, list):
            if not key.isdigit() or (len(key) > 1 and key[0] == "0"):
                raise IndexError(key)
            index = int(key)
            if index >= len(current):
                raise IndexError(key)
            current = current[index]
        else:
            raise KeyError(key)
    return current

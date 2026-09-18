"""RFC 6901 JSON Pointer resolution."""


def resolve(document, pointer):
    """Resolve a JSON Pointer against a parsed JSON document.

    - "" returns the whole document.
    - "/a/b" walks into nested objects and lists.
    - "~1" decodes to "/" and "~0" to "~", unescaped in that order.
    - Raise KeyError for a missing object key.
    - Raise IndexError for a list index that is absent, not an integer, or
      written with a leading zero ("01" is not a valid index).
    """
    raise NotImplementedError

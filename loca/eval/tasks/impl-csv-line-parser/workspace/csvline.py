"""A single-line CSV field splitter."""


def parse_line(line):
    """Split one CSV line into a list of fields.

    - Fields are separated by commas.
    - A field starting with a double quote may contain commas.
    - Inside a quoted field, "" means one literal quote character.
    - Quotes are only special at the start of a field; in the middle of an
      unquoted field they are ordinary characters.
    - Empty fields are preserved, including a trailing empty field.
    """
    raise NotImplementedError

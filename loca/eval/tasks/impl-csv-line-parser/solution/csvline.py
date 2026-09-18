"""A single-line CSV field splitter."""


def parse_line(line):
    """Split one CSV line into a list of fields."""
    fields = []
    index = 0
    length = len(line)
    while True:
        if index < length and line[index] == '"':
            index += 1
            buffer = []
            while index < length:
                char = line[index]
                if char == '"':
                    if index + 1 < length and line[index + 1] == '"':
                        buffer.append('"')
                        index += 2
                        continue
                    index += 1
                    break
                buffer.append(char)
                index += 1
            fields.append("".join(buffer))
        else:
            start = index
            while index < length and line[index] != ",":
                index += 1
            fields.append(line[start:index])
        if index < length and line[index] == ",":
            index += 1
            continue
        break
    return fields

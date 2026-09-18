"""A little bag of items."""


def add_item(item, items=[]):
    items.append(item)
    return items


def add_many(new_items, items=[]):
    for item in new_items:
        items.append(item)
    return items

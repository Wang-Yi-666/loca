"""A little bag of items."""


def add_item(item, items=None):
    if items is None:
        items = []
    items.append(item)
    return items


def add_many(new_items, items=None):
    if items is None:
        items = []
    for item in new_items:
        items.append(item)
    return items

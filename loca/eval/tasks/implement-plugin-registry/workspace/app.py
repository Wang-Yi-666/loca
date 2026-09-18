"""A small app built on the plugin registry."""

from plugins import get, names, register


def shout(text):
    return text.upper()


def whisper(text):
    return text.lower()


def build():
    """Register the built-in plugins and return the sorted names."""
    register("shout", shout)
    register("whisper", whisper)
    return names()


def apply(name, text):
    """Run the plugin called `name` on `text`."""
    return get(name)(text)

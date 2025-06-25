from .utils import *

# Auto-import all submodules
import pkgutil
import sys

for importer, modname, ispkg in pkgutil.iter_modules(__path__):
    if modname not in sys.modules:
        __import__(f"{__name__}.{modname}")

__all__ = [
    "ascii_to_scancode",
    "build_scancode",
    "scancode_to_ascii",
    "merge_scancodes",
    "string_to_scancodes",
]

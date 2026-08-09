import sys

# Version metadata
__version__ = "3.0.0rc1"

# Module alias for case-sensitive import compatibility
sys.modules["dicodePing"] = sys.modules[__name__]

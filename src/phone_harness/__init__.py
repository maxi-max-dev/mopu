"""Compatibility namespace for installations predating Mopu.

New integrations should import mopu. The legacy module path continues to load
from the same source tree, with the same state resolver and protocol.
"""
from mopu import __version__, __path__

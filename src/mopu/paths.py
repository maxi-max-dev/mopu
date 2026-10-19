"""Share existing private state across both command names; never silently fork it."""
from pathlib import Path

def default_state(home=None):
    root = Path(home) if home is not None else Path.home()
    legacy = root / '.local/share/phone-harness'
    current = root / '.local/share/mopu'
    # Existing legacy data takes precedence even when a new directory was created.
    # Explicit --state always overrides this resolver.
    return legacy if legacy.exists() else current

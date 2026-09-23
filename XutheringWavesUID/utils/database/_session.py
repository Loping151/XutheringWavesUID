from gsuid_core.utils.database.base_models import with_session

try:
    from gsuid_core.utils.database.base_models import with_read_session
except ImportError:
    with_read_session = with_session

__all__ = ["with_session", "with_read_session"]

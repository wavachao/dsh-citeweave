"""Serialize GPU experiments and interactive generation on this Linux server."""

from contextlib import contextmanager

from . import config


@contextmanager
def gpu_session(blocking=True):
    import fcntl

    directory = config.ROOT / "work"
    directory.mkdir(exist_ok=True)
    with (directory / "gpu.lock").open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

import os

from core.process_tracker import pid_exists


def test_pid_exists_current_process_is_non_destructive():
    assert pid_exists(os.getpid()) is True


def test_pid_exists_rejects_invalid_pid():
    assert pid_exists(-1) is False

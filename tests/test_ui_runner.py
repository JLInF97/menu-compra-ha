"""Limpieza del servidor portátil; dobles de procesos explícitos, sin matar procesos reales."""
import subprocess
from types import SimpleNamespace

import pytest

from tools.verify_ui_v5_1 import stop_server


class ProcessFixture:
    pid = 123

    def __init__(self, *, ended=False, wait_timeout=False):
        self.ended = ended
        self.wait_timeout = wait_timeout
        self.events = []

    def poll(self):
        return 0 if self.ended else None

    def terminate(self):
        self.events.append('terminate')

    def kill(self):
        self.events.append('kill')

    def wait(self, timeout):
        assert timeout == 10
        self.events.append('wait')
        if self.wait_timeout:
            self.wait_timeout = False
            raise subprocess.TimeoutExpired('fixture', timeout)


def test_posix_terminates_and_waits():
    server = ProcessFixture()
    stop_server(server, windows=False)
    assert server.events == ['terminate', 'wait']


def test_posix_timeout_uses_kill_and_waits():
    server = ProcessFixture(wait_timeout=True)
    stop_server(server, windows=False)
    assert server.events == ['terminate', 'wait', 'kill', 'wait']


def test_already_stopped_server_is_not_killed():
    server = ProcessFixture(ended=True)
    stop_server(server, windows=True)
    assert server.events == []


def test_windows_kills_only_the_fixture_tree(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert kwargs['timeout'] == 15 and kwargs['check'] is False
        return SimpleNamespace(returncode=0, stderr='')
    monkeypatch.setattr('tools.verify_ui_v5_1.subprocess.run', run)
    server = ProcessFixture()
    stop_server(server, windows=True)
    assert calls == [['taskkill','/PID','123','/T','/F']]
    assert server.events == ['wait']


def test_windows_cleanup_failure_is_not_silenced(monkeypatch):
    monkeypatch.setattr('tools.verify_ui_v5_1.subprocess.run',
                        lambda *a, **k: SimpleNamespace(returncode=1, stderr='fallo fixture'))
    with pytest.raises(RuntimeError, match='cerrar el árbol'):
        stop_server(ProcessFixture(), windows=True)

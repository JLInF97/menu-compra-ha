"""Pruebas locales del smoke; los dobles Docker NO prueban un daemon real."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import pytest
import uvicorn
import yaml

from app.db import Database
from app.main import create_app
from tools import check_container as checker


def run_probe(source, *args):
    environment = os.environ.copy()
    environment["MENU_COMPRA_DEV"] = "0"
    return subprocess.run([sys.executable, "-c", source, *map(str, args)],
                          capture_output=True, text=True, timeout=20, env=environment)


@pytest.fixture
def production_server(tmp_path, request):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    base = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(create_app(tmp_path, development=False), log_level="error",
                                           proxy_headers=getattr(request, "param", False)))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "No arrancó el servidor HTTP local de prueba"
        yield base
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


def test_http_probe_against_real_production_http(production_server):
    result = run_probe(checker.HTTP_PROBE, production_server)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["health"] == {"status": "ok", "version": "1.1.0"}
    assert len(report["denied"]) == 20
    assert all(check["status"] == 403 for check in report["denied"])
    assert report["bridge_disabled"] is True


@pytest.mark.parametrize("production_server", [True], indirect=True)
def test_http_probe_detects_trusting_forwarded_headers(production_server):
    # Fixture deliberadamente insegura: el smoke debe detectar la regresión.
    result = run_probe(checker.HTTP_PROBE, production_server)
    assert result.returncode != 0
    assert "X-Forwarded-For" in result.stderr and "AssertionError" in result.stderr


def test_http_probe_rejects_development_environment():
    environment = os.environ.copy()
    environment["MENU_COMPRA_DEV"] = "1"
    result = subprocess.run([sys.executable, "-c", checker.HTTP_PROBE], env=environment,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "Producción desactivada" in result.stderr


def test_data_probe_is_read_only_for_the_application(tmp_path):
    Database(tmp_path).initialize()
    app_database = tmp_path / "menu_compra.sqlite3"
    original = app_database.read_bytes()
    before = run_probe(checker.DATA_PROBE, "prepare", "testigo-ci", tmp_path)
    assert before.returncode == 0, before.stderr
    assert app_database.read_bytes() == original
    # La misma migración que se ejecuta al reiniciar: los contadores pueden avanzar.
    Database(tmp_path).initialize()
    restarted = app_database.read_bytes()
    after = run_probe(checker.DATA_PROBE, "verify", "testigo-ci", tmp_path)
    assert after.returncode == 0, after.stderr
    assert json.loads(before.stdout) == json.loads(after.stdout)
    assert app_database.read_bytes() == restarted
    assert (tmp_path / ".ci-persistence.sqlite3").is_file()


def test_data_probe_rejects_lost_or_wrong_witness(tmp_path):
    Database(tmp_path).initialize()
    assert run_probe(checker.DATA_PROBE, "prepare", "original", tmp_path).returncode == 0
    assert run_probe(checker.DATA_PROBE, "verify", "incorrecto", tmp_path).returncode != 0
    (tmp_path / ".ci-persistence.sqlite3").unlink()
    result = run_probe(checker.DATA_PROBE, "verify", "original", tmp_path)
    assert result.returncode != 0
    assert "Se perdió el testigo" in result.stderr


def args():
    return argparse.Namespace(platform="linux/amd64", build_timeout=30, startup_timeout=2)


def docker_fixture(monkeypatch, fail=None, published=False, platform="amd64"):
    calls = []

    def fake_docker(*command, timeout=60, check=True):
        calls.append((command, timeout))
        if fail and command[0] == fail:
            raise RuntimeError("fallo Docker de fixture")
        if command[:2] == ("image", "inspect"):
            output = [{"Os": "linux", "Architecture": platform}]
        elif command[0] == "inspect":
            output = [{"HostConfig": {"PortBindings": {"8099/tcp": [{}]} if published else {}, "PublishAllPorts": False},
                       "Config": {"Env": ["MENU_COMPRA_DEV=0", "MENU_COMPRA_DATA_DIR=/data"]}}]
        else:
            output = []
        return subprocess.CompletedProcess(command, 0, json.dumps(output), "")

    monkeypatch.setattr(checker, "docker", fake_docker)
    monkeypatch.setattr(checker, "wait_ready", lambda *a: {"health": "fixture explícita, no Docker real"})
    monkeypatch.setattr(checker, "exec_probe", lambda *a: {"app_sha256": "fixture-snapshot", "volume_probe": "ok"})
    return calls


def test_orchestration_never_publishes_or_overrides_production(monkeypatch):
    calls = docker_fixture(monkeypatch)
    report = {}
    checker.smoke(args(), report)
    commands = [command for command, _ in calls]
    build = next(command for command in commands if command[:2] == ("buildx", "build"))
    assert "--push=false" in build and "--load" in build
    assert build[-1] == checker.ROOT / "menu_compra"
    run = next(command for command in commands if command[0] == "run")
    assert not ({"-p", "-P", "--publish", "--publish-all", "-e", "--env", "--env-file", "--privileged"} & set(run))
    assert "--network=none" in run
    assert any(command[0] == "restart" for command in commands)
    assert any(command[:2] == ("rm", "--force") for command in commands)
    assert any(command[:2] == ("volume", "rm") for command in commands)
    assert any(command[:2] == ("image", "rm") for command in commands)
    assert report["published_ports"] is False
    assert report["cleanup_errors"] == []
    assert all(0 < timeout <= 60 for _, timeout in calls)


@pytest.mark.parametrize("failure", ["buildx", "run", "restart"])
def test_failure_always_cleans_owned_resources(monkeypatch, failure):
    calls = docker_fixture(monkeypatch, fail=failure)
    with pytest.raises(RuntimeError, match="fallo Docker"):
        checker.smoke(args(), {})
    commands = [command for command, _ in calls]
    assert any(command[:2] == ("image", "rm") for command in commands)
    if failure != "buildx":
        assert any(command[:2] == ("volume", "rm") for command in commands)
        assert any(command[:2] == ("rm", "--force") for command in commands)


@pytest.mark.parametrize("published,platform,error", [(True, "amd64", "puertos"), (False, "arm64", "Arquitectura")])
def test_inspect_rejects_wrong_architecture_or_ports(monkeypatch, published, platform, error):
    docker_fixture(monkeypatch, published=published, platform=platform)
    with pytest.raises(RuntimeError, match=error):
        checker.smoke(args(), {})


def test_restart_data_change_is_not_success(monkeypatch):
    docker_fixture(monkeypatch)
    snapshots = iter([{"digest": "antes"}, {"digest": "después"}])
    monkeypatch.setattr(checker, "exec_probe", lambda *a: next(snapshots))
    with pytest.raises(RuntimeError, match="Datos de /data alterados"):
        checker.smoke(args(), {})


def test_cli_reports_missing_docker_without_trying_to_start_it(monkeypatch, tmp_path, capsys):
    commands = []

    def unavailable(*command, **kwargs):
        commands.append(command)
        raise FileNotFoundError("Docker no está disponible: fixture")

    monkeypatch.setattr(checker, "docker", unavailable)
    output = tmp_path / "result.json"
    assert checker.main(["--output", str(output)]) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "failed" and "Docker no está disponible" in report["error"]
    assert len(commands) == 1 and commands[0][0] == "info"
    assert json.loads(capsys.readouterr().out) == report


def test_docker_runner_has_timeout_and_no_shell(monkeypatch):
    def completed(command, **kwargs):
        assert command == ["docker", "info"]
        assert kwargs == {"capture_output": True, "text": True, "timeout": 7, "check": False}
        return subprocess.CompletedProcess(command, 0, "ok", "")
    monkeypatch.setattr(checker.subprocess, "run", completed)
    assert checker.docker("info", timeout=7).stdout == "ok"


def test_workflow_has_read_only_permissions_platforms_and_pinned_actions():
    workflow_path = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
    workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"push", "pull_request", "workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["pruebas"]["strategy"]["matrix"]["python"] == ["3.12", "3.14"]
    assert workflow["jobs"]["contenedor"]["strategy"]["matrix"]["arch"] == ["amd64", "arm64"]
    for job in workflow["jobs"].values():
        assert job["runs-on"] == "ubuntu-24.04"
        for step in job["steps"]:
            if "uses" in step:
                sha = step["uses"].split("@", 1)[1]
                assert len(sha) == 40 and all(character in "0123456789abcdef" for character in sha)

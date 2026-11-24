"""Core 2026.11.1 helper/AST fixtures, NOT a running HA/Supervisor instance.

Real probatio schemas and actual BridgeClient/FastAPI TCP health are exercised.
HA wrapper methods/selectors/Supervisor records are explicit isolated fixtures;
no fake homeassistant module is installed globally.
"""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

import pytest

from test_ha_support import aiohttp, api, pure_module, real_backend
from test_ha_support import anyio_backend as anyio_backend

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "menu_compra"
discovery = pure_module("discovery")
settings = pure_module("settings")
KEY = "explicit-supervisor-fixture-" + "x" * 43
NEW_KEY = "rotated-supervisor-fixture-" + "y" * 43


def announcement(slug="local_menu_compra", *, key=KEY, **overrides):
    config = {"base_url": f"http://{slug.replace('_', '-')}:8099",
              "api_key": key, "protocol_version": 1}
    config.update(overrides)
    return SimpleNamespace(service="menu_compra", addon=slug, config=config,
                           uuid="explicit-discovery-uuid")


def app_from(record):
    return discovery.parse_discovery(record.service, record.addon, record.config)


def entry_fixture(app=None, *, managed=True, listeners=True):
    app = app or app_from(announcement())
    data = {**app.connection(), "telegram_event_entity": "event.bot_original",
            "allowed_chats": [-100111], "custom_data": "preserved"}
    if not managed:
        data.pop("app_slug")
    return SimpleNamespace(entry_id="unchanged-entry-id", unique_id="menu_compra", source="user", data=data,
        options={"telegram_event_entity": "event.bot_options", "allowed_chats": [-100222, 123],
                 "api_key": "old-key-" + "z" * 43, "custom_option": "preserved"},
        update_listeners=("reload-listener-fixture",) if listeners else ())


@pytest.mark.parametrize("slug", ["local_menu_compra", "012abcde_menu_compra"])
def test_strict_discovery_valid_slug_and_no_secret_repr(slug):
    record = announcement(slug)
    app = app_from(record)
    assert app.base_url == record.config["base_url"]
    assert app.connection()["api_key"] == KEY
    assert KEY not in repr(app)


@pytest.mark.parametrize("slug", ["menu_compra", "local_other", "012abcde_other", "012ABCDE_menu_compra",
                                 "abc_menu_compra", "local_menu_compra.evil", "local_menu_compra\n"])
def test_rejects_foreign_installation_slugs(slug):
    with pytest.raises(discovery.DiscoveryError) as caught:
        app_from(announcement(slug))
    assert KEY not in str(caught.value)


@pytest.mark.parametrize("overrides", [
    {"base_url": "http://127.0.0.1:8099"}, {"base_url": "http://supervisor:8099"},
    {"base_url": "http://local-menu-compra:8099/"}, {"base_url": "https://local-menu-compra:8099"},
    {"base_url": "http://local-menu-compra:8098"}, {"base_url": "http://user:secret@local-menu-compra:8099"},
    {"base_url": "http://local-menu-compra:8099?key=secret"}, {"protocol_version": True},
    {"protocol_version": "1"}, {"protocol_version": 2}, {"api_key": "short"},
    {"api_key": "a" * 129}, {"api_key": "\n" + KEY}, {"api_key": None},
])
def test_rejects_untrusted_origin_protocol_or_key(overrides):
    with pytest.raises(discovery.DiscoveryError) as caught:
        app_from(announcement(**overrides))
    assert KEY not in str(caught.value) and "secret" not in str(caught.value)


def test_foreign_service_and_duplicate_discoveries_fail_closed():
    foreign = announcement()
    foreign.service = "mqtt"
    invalid = announcement(base_url="http://attacker:8099")
    valid = announcement()
    assert discovery.parse_discoveries([foreign, invalid, valid, valid]) == [app_from(valid)]
    with pytest.raises(discovery.DiscoveryError) as caught:
        discovery.parse_discoveries([valid, announcement(key=NEW_KEY)])
    assert KEY not in str(caught.value) and NEW_KEY not in str(caught.value)
    with pytest.raises(discovery.DiscoveryError):
        discovery.parse_discovery("mqtt", valid.addon, valid.config)


def test_entry_update_preserves_telegram_and_refreshes_old_options_override():
    app = app_from(announcement())
    entry = entry_fixture(app)
    old = copy.deepcopy(entry)
    updated = app_from(announcement(key=NEW_KEY))
    data, options = discovery.entry_update(updated, entry)
    assert entry == old  # Pure helper does not mutate before a health check.
    assert data["api_key"] == options["api_key"] == NEW_KEY
    for field in ("telegram_event_entity", "allowed_chats", "custom_data"):
        assert data[field] == old.data[field]
    for field in ("telegram_event_entity", "allowed_chats", "custom_option"):
        assert options[field] == old.options[field]
    assert discovery.matches_entry(app, entry_fixture(app, managed=False))
    entry.data["app_slug"] = "012abcde_menu_compra"
    assert not discovery.matches_entry(app, entry)
    with pytest.raises(discovery.DiscoveryError):
        discovery.entry_update(app, entry)


@pytest.fixture
def flow_fixture():
    """Actual flow AST + real probatio, explicit selector/flow-method fixtures."""
    try:
        import probatio as vol
    except (ImportError, SyntaxError):
        pytest.skip("Run Core's probatio schemas with Python 3.14")
    original_ha = {name: value for name, value in sys.modules.items() if name == "homeassistant" or name.startswith("homeassistant.")}

    class FlowMethodsFixture:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

        def __init__(self):
            self.entries = []
            self.updated = []
            self.reloaded = []
            self.hass = SimpleNamespace(config=SimpleNamespace(components={"hassio"}))

        def _async_current_entries(self):
            return self.entries

        def _get_reconfigure_entry(self):
            return self.entries[0]

        def _get_reauth_entry(self):
            return self.entries[0]

        def async_abort(self, **kwargs):
            return {"type": "abort", **kwargs}

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_show_menu(self, **kwargs):
            return {"type": "menu", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

        async def async_set_unique_id(self, value):
            self.unique_id = value

        def _abort_if_unique_id_configured(self):
            assert not self.entries

        def async_update_and_abort(self, entry, **kwargs):
            changed = (entry.data != kwargs["data"] or entry.options != kwargs["options"]
                       or entry.unique_id != kwargs.get("unique_id", entry.unique_id))
            if changed:
                self.updated.append(entry.entry_id)
            entry.data = kwargs["data"]
            entry.options = kwargs["options"]
            entry.unique_id = kwargs.get("unique_id", entry.unique_id)
            return self.async_abort(reason=kwargs.get("reason", "reauth_successful"))

        def async_update_reload_and_abort(self, entry, **kwargs):
            changed = (entry.data != kwargs["data"] or entry.options != kwargs["options"]
                       or entry.unique_id != kwargs.get("unique_id", entry.unique_id))
            if changed or kwargs.get("reload_even_if_entry_is_unchanged", True):
                self.reloaded.append(entry.entry_id)
            return self.async_update_and_abort(entry, **kwargs)

    state = SimpleNamespace(records=[announcement()], discovery_error=None, health_error=None,
                            health_calls=[], list_calls=0)

    async def discover_fixture(hass):
        state.list_calls += 1
        if state.discovery_error:
            raise state.discovery_error
        return discovery.parse_discoveries(state.records)

    class HealthClientFixture:
        def __init__(self, session, base_url, api_key):
            self.base_url, self.api_key = base_url, api_key

        async def health(self):
            state.health_calls.append((self.base_url, self.api_key))
            if state.health_error:
                raise state.health_error
            return {"status": "ok", "version": "1.1.0"}

    selectors = SimpleNamespace(TextSelector=lambda *a, **k: str, TextSelectorConfig=dict,
        TextSelectorType=SimpleNamespace(URL="url", PASSWORD="password"),
        EntitySelector=lambda *a, **k: str, EntitySelectorConfig=dict,
        SelectSelector=lambda config: vol.In(config["options"]), SelectSelectorConfig=dict)
    namespace = {"vol": vol, "selector": selectors, "DEFAULT_URL": api.DEFAULT_URL,
        "config_entries": SimpleNamespace(ConfigFlow=FlowMethodsFixture, OptionsFlow=FlowMethodsFixture),
        "callback": lambda f: f, "DOMAIN": settings.DOMAIN, "normalize_settings": settings.normalize_settings,
        "async_get_clientsession": lambda hass: None, "BridgeClient": HealthClientFixture,
        "AuthenticationError": api.AuthenticationError, "BridgeError": api.BridgeError,
        "async_discover": discover_fixture,
        # Registry fixture checks actual validate(), but is not an HA registry.
        "er": SimpleNamespace(async_get=lambda hass: SimpleNamespace(async_get=lambda entity: None))}
    namespace.update({name: getattr(discovery, name) for name in (
        "DiscoveryError", "DiscoveryUnavailable", "entry_update", "matches_entry", "parse_discovery")})
    source = ast.parse((COMPONENT / "config_flow.py").read_text(encoding="utf-8"))
    body = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    body += [node for node in source.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])),
                 "<actual-flow-with-isolated-HA-method-fixtures>", "exec"), namespace)
    yield SimpleNamespace(ns=namespace, state=state, flow=namespace["MenuCompraConfigFlow"](),
                          Options=namespace["MenuCompraOptionsFlow"], vol=vol)
    assert original_ha == {name: value for name, value in sys.modules.items()
                           if name == "homeassistant" or name.startswith("homeassistant.")}


@pytest.mark.anyio
@pytest.mark.parametrize("source", ["user", "hassio"])
async def test_automatic_pairing_no_credentials_form(flow_fixture, source):
    fixture = flow_fixture
    if source == "user":
        result = await fixture.flow.async_step_user()
    else:
        record = fixture.state.records[0]
        result = await fixture.flow.async_step_hassio(SimpleNamespace(config=record.config,
            name="Untrusted name " + KEY, slug=record.addon, uuid=record.uuid))
    assert result["type"] == "create_entry" and fixture.flow.unique_id == "menu_compra"
    assert result["data"]["api_key"] == KEY
    assert result["data"]["app_slug"] == "local_menu_compra"
    assert result["data"]["allowed_chats"] == []
    assert fixture.state.list_calls == 1
    assert fixture.state.health_calls == [("http://local-menu-compra:8099", KEY)]
    assert result["title"] == "Menú y Compra"


@pytest.mark.anyio
async def test_manual_is_advanced_and_schema_remains_compatible(flow_fixture):
    f = flow_fixture
    f.state.discovery_error = discovery.DiscoveryUnavailable(KEY)
    menu = await f.flow.async_step_user()
    assert menu["menu_options"] == ["automatic", "manual"] and KEY not in repr(menu)
    form = await f.flow.async_step_manual()
    assert form["step_id"] == "manual"
    with pytest.raises(f.vol.Invalid):
        form["data_schema"]({"base_url": "http://manual:8099"})
    data = form["data_schema"]({"base_url": "http://manual:8099", "api_key": KEY})
    result = await f.flow.async_step_manual(data)
    assert result["type"] == "create_entry" and "app_slug" not in result["data"]
    current = {"api_key": KEY, "allowed_chats": [-100], "telegram_event_entity": "event.bot"}
    schema = f.ns["form_schema"](current)
    cleared = schema({"base_url": "http://manual:8099"})
    assert "api_key" not in cleared and not cleared.get("allowed_chats")
    assert KEY not in repr(schema)


@pytest.mark.anyio
async def test_multiple_apps_require_public_selection_and_refresh_secret(flow_fixture):
    f = flow_fixture
    f.state.records.append(announcement("012abcde_menu_compra"))
    form = await f.flow.async_step_user()
    assert form["step_id"] == "select_app" and not f.state.health_calls
    assert KEY not in repr(form) and "api_key" not in repr(form)
    assert form["data_schema"]({"app_slug": "local_menu_compra"}) == {"app_slug": "local_menu_compra"}
    with pytest.raises(f.vol.Invalid):
        form["data_schema"]({"app_slug": "unknown"})
    invalid = await f.flow.async_step_select_app({"app_slug": KEY})
    assert invalid["errors"] == {"base": "invalid_selection"} and KEY not in repr(invalid)
    f.state.records[0] = announcement(key=NEW_KEY)
    result = await f.flow.async_step_select_app({"app_slug": "local_menu_compra"})
    assert result["data"]["api_key"] == NEW_KEY and f.state.list_calls == 2


@pytest.mark.anyio
async def test_push_also_checks_multiple_apps(flow_fixture):
    f = flow_fixture
    f.state.records.append(announcement("012abcde_menu_compra"))
    record = f.state.records[0]
    result = await f.flow.async_step_hassio(SimpleNamespace(config=record.config, slug=record.addon))
    assert result["step_id"] == "select_app" and not f.state.health_calls


@pytest.mark.anyio
@pytest.mark.parametrize("managed", [True, False])
async def test_rediscovery_adopts_same_origin_preserves_id_and_all_telegram(flow_fixture, managed):
    f = flow_fixture
    entry = entry_fixture(managed=managed)
    f.flow.entries = [entry]
    before = copy.deepcopy(entry)
    f.state.records = [announcement(key=NEW_KEY)]
    result = await f.flow.async_step_user()
    assert result == {"type": "abort", "reason": "automatic_updated"}
    assert f.flow.updated == [before.entry_id] and f.flow.reloaded == []
    assert entry.entry_id == before.entry_id and entry.unique_id == "menu_compra"
    assert entry.data["app_slug"] == "local_menu_compra"
    assert entry.data["api_key"] == entry.options["api_key"] == NEW_KEY
    for field in ("allowed_chats", "telegram_event_entity"):
        assert entry.data[field] == before.data[field]
        assert entry.options[field] == before.options[field]
    assert entry.options["custom_option"] == "preserved" and entry.data["custom_data"] == "preserved"


@pytest.mark.anyio
@pytest.mark.parametrize("managed", [True, False])
async def test_different_installation_cannot_replace_existing_data(flow_fixture, managed):
    f = flow_fixture
    entry = entry_fixture(managed=managed)
    f.flow.entries = [entry]
    before = copy.deepcopy(entry)
    record = announcement("012abcde_menu_compra")
    f.state.records = [record]
    result = await f.flow.async_step_user()
    assert result["reason"] == "different_installation"
    result = await f.flow.async_step_hassio(SimpleNamespace(config=record.config, slug=record.addon))
    assert result["reason"] == "different_installation"
    assert entry == before and not f.flow.updated and not f.state.health_calls


@pytest.mark.anyio
@pytest.mark.parametrize("step", ["reauth", "reconfigure"])
@pytest.mark.parametrize("listeners", [True, False])
async def test_managed_reauth_reconfigure_refetch_supervisor_without_credentials(flow_fixture, step, listeners):
    f = flow_fixture
    entry = entry_fixture(listeners=listeners)
    f.flow.entries = [entry]
    f.state.records = [announcement(key=NEW_KEY), announcement("012abcde_menu_compra")]
    result = await (f.flow.async_step_reauth(entry.data) if step == "reauth" else f.flow.async_step_reconfigure())
    assert result["reason"] == "automatic_updated" and f.state.list_calls == 1
    assert entry.options["api_key"] == NEW_KEY and entry.options["allowed_chats"] == [-100222, 123]
    assert f.flow.reloaded == ([] if listeners else [entry.entry_id])


@pytest.mark.anyio
@pytest.mark.parametrize("error,code", [(api.AuthenticationError(KEY), "invalid_auth"),
                                        (api.BridgeError(KEY), "cannot_connect")])
async def test_health_failure_is_safe_and_never_mutates_entry(flow_fixture, error, code):
    f = flow_fixture
    entry = entry_fixture()
    before = copy.deepcopy(entry)
    f.flow.entries = [entry]
    f.state.health_error = error
    result = await f.flow.async_step_user()
    assert result["step_id"] == "automatic" and result["errors"] == {"base": code}
    assert result["data_schema"]({}) == {} and KEY not in repr(result)
    assert entry == before and not f.flow.updated
    f.state.health_error = None
    assert (await f.flow.async_step_automatic({}))["reason"] == "automatic_updated"


@pytest.mark.anyio
async def test_supervisor_failure_missing_discovery_and_duplicate_are_safe(flow_fixture):
    f = flow_fixture
    f.flow.entries = [entry_fixture()]
    before = copy.deepcopy(f.flow.entries[0])
    f.state.discovery_error = discovery.DiscoveryUnavailable(KEY)
    result = await f.flow.async_step_reauth(before.data)
    assert result["errors"] == {"base": "supervisor_unavailable"} and KEY not in repr(result)
    f.state.discovery_error = None
    f.state.records = [announcement("012abcde_menu_compra")]
    result = await f.flow.async_step_reauth(before.data)
    assert result["errors"] == {"base": "no_discoveries"}
    f.state.records = [announcement(), announcement(key=NEW_KEY)]
    result = await f.flow.async_step_automatic({})
    assert result["errors"] == {"base": "invalid_discovery"}
    assert f.flow.entries[0] == before and not f.state.health_calls and KEY not in repr(result)


@pytest.mark.anyio
async def test_telegram_options_clear_explicitly_without_connection_fields(flow_fixture):
    f = flow_fixture
    options = f.Options()
    entry = entry_fixture()
    options.config_entry = entry
    menu = await options.async_step_init()
    assert menu["menu_options"] == ["telegram", "advanced"]
    form = await options.async_step_telegram()
    assert KEY not in repr(form) and "api_key" not in repr(form)
    cleared = form["data_schema"]({})
    result = await options.async_step_telegram(cleared)
    assert result["data"]["allowed_chats"] == [] and result["data"]["telegram_event_entity"] == ""
    assert result["data"]["api_key"] == entry.options["api_key"]
    assert result["data"]["custom_option"] == "preserved"
    assert "app_slug" not in result["data"]
    forbidden = await options.async_step_advanced({"base_url": "http://another-app:8099"})
    assert forbidden["errors"] == {"base": "different_installation"}


@pytest.mark.anyio
@pytest.mark.parametrize("listeners", [True, False])
async def test_repeated_announcement_is_idempotent_and_preserves_legacy_source(flow_fixture, listeners):
    f = flow_fixture
    entry = entry_fixture(listeners=listeners)
    entry.options["api_key"] = KEY
    before = copy.deepcopy(entry)
    f.flow.entries = [entry]
    for _ in range(2):
        result = await f.flow.async_step_user()
        assert result["reason"] == "automatic_updated"
    assert entry == before and entry.source == "user"
    assert f.flow.updated == [] and f.flow.reloaded == []
    assert len(f.state.health_calls) == 2


@pytest.mark.anyio
async def test_entry_created_during_health_is_adopted_not_duplicated(flow_fixture):
    f = flow_fixture
    original = f.ns["BridgeClient"]
    entry = entry_fixture()
    class ConcurrentHealthFixture(original):
        async def health(self):
            result = await super().health()
            f.flow.entries.append(entry)
            return result
    f.ns["BridgeClient"] = ConcurrentHealthFixture
    result = await f.flow.async_step_user()
    assert result["reason"] == "automatic_updated"
    assert f.flow.entries == [entry] and f.flow.updated == [entry.entry_id]
    assert not hasattr(f.flow, "unique_id")  # Creation path was never reached.


@pytest.mark.anyio
async def test_selected_discovery_removed_during_form_is_not_reused(flow_fixture):
    f = flow_fixture
    f.state.records.append(announcement("012abcde_menu_compra"))
    assert (await f.flow.async_step_user())["step_id"] == "select_app"
    f.state.records = [announcement("012abcde_menu_compra")]
    result = await f.flow.async_step_select_app({"app_slug": "local_menu_compra"})
    assert result["errors"] == {"base": "discovery_changed"} and not f.state.health_calls


@pytest.mark.anyio
async def test_invalid_push_and_credential_rotation_race_are_safe(flow_fixture):
    f = flow_fixture
    result = await f.flow.async_step_hassio(SimpleNamespace(slug="local_other", config=announcement().config))
    assert result["reason"] == "invalid_discovery" and not f.state.health_calls
    record = announcement(key=NEW_KEY)
    result = await f.flow.async_step_hassio(SimpleNamespace(slug=record.addon, config=record.config))
    assert result["errors"] == {"base": "discovery_changed"}
    assert KEY not in repr(result) and NEW_KEY not in repr(result)


@pytest.mark.anyio
async def test_manual_reauth_retains_old_key_and_unknown_settings_without_adoption(flow_fixture):
    f = flow_fixture
    entry = entry_fixture(managed=False, listeners=False)
    # Explicitly no Telegram: test the manual connection path independent of
    # registry selection. The separate options test checks deliberate clearing.
    entry.options.update(telegram_event_entity="", allowed_chats=[])
    f.flow.entries = [entry]
    form = await f.flow.async_step_reauth(entry.data)
    assert form["step_id"] == "reauth_confirm" and not f.state.list_calls
    result = await f.flow.async_step_reauth_confirm({"base_url": entry.data["base_url"]})
    assert result["type"] == "abort" and "app_slug" not in entry.data
    assert entry.data["api_key"] == entry.options["api_key"]
    assert entry.data["custom_data"] == entry.options["custom_option"] == "preserved"
    assert entry.source == "user" and f.flow.reloaded == [entry.entry_id]


@pytest.mark.anyio
async def test_authenticated_supervisor_list_wrapper_ast_fixture():
    """Execute actual retrieval body; replace imports only, not global modules."""
    source = ast.parse((COMPONENT / "discovery.py").read_text(encoding="utf-8"))
    function = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_discover")
    imports = [node for node in function.body if isinstance(node, ast.ImportFrom)]
    assert any(node.module == "homeassistant.components.hassio.handler" and node.names[0].name == "get_supervisor_client" for node in imports)
    function.body = [node for node in function.body if not isinstance(node, ast.ImportFrom)]
    state = SimpleNamespace(calls=0, error=None)
    class SupervisorErrorFixture(Exception):
        pass
    async def list_fixture():
        state.calls += 1
        if state.error:
            raise state.error
        return [announcement()]
    def get_client_fixture(hass):
        assert hass is expected_hass
        return SimpleNamespace(discovery=SimpleNamespace(list=list_fixture))
    expected_hass = SimpleNamespace(config=SimpleNamespace(components={"hassio"}))
    namespace = {"DiscoveryUnavailable": discovery.DiscoveryUnavailable, "parse_discoveries": discovery.parse_discoveries,
                 "get_supervisor_client": get_client_fixture, "SupervisorError": SupervisorErrorFixture,
                 "ClientError": aiohttp.ClientError}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                 "<actual-supervisor-list-with-isolated-client-fixture>", "exec"), namespace)
    actual = namespace["async_discover"]
    assert await actual(expected_hass) == [app_from(announcement())] and state.calls == 1
    state.error = SupervisorErrorFixture(KEY)
    with pytest.raises(discovery.DiscoveryUnavailable) as caught:
        await actual(expected_hass)
    assert KEY not in str(caught.value) and caught.value.__suppress_context__
    expected_hass.config.components.clear()
    with pytest.raises(discovery.DiscoveryUnavailable):
        await actual(expected_hass)
    assert state.calls == 2


@pytest.mark.anyio
async def test_real_bridge_health_and_pairing_over_tcp_with_explicit_dns_fixture(flow_fixture):
    """Actual backend + client; fixture maps canonical app DNS to a scratch port."""
    f = flow_fixture
    async with real_backend() as backend:
        class LoopbackAppDNSFixture(aiohttp.abc.AbstractResolver):
            async def resolve(self, host, port=0, family=socket.AF_INET):
                assert host == "local-menu-compra" and port == 8099
                return [{"hostname": host, "host": "127.0.0.1", "port": int(backend.url.rsplit(":", 1)[1]),
                         "family": socket.AF_INET, "proto": 0, "flags": 0}]
            async def close(self):
                pass
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=LoopbackAppDNSFixture())) as session:
            f.ns["BridgeClient"] = api.BridgeClient
            f.ns["async_get_clientsession"] = lambda hass: session
            f.state.records = [announcement(key=backend.token)]
            result = await f.flow.async_step_user()
            assert result["type"] == "create_entry" and result["data"]["api_key"] == backend.token
            assert (await api.BridgeClient(session, "http://local-menu-compra:8099", backend.token).health())["status"] == "ok"
            f.state.records = [announcement(key=KEY)]
            result = await f.flow.async_step_user()
            assert result["errors"] == {"base": "invalid_auth"} and backend.token not in repr(result)


@pytest.mark.anyio
@pytest.mark.parametrize("version", ["0.6.0", "1.0.0", "1.1.0", "unsupported", None, [], {}])
async def test_health_compatibility_over_real_tcp_version_fixture(version):
    """Explicit version-response fixture, not a historical backend instance."""
    import asyncio
    async def handler(reader, writer):
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            assert request.startswith(b"GET /bridge/v1/health HTTP/1.1\r\n")
            assert f"Bearer {KEY}".encode() in request
            payload = json.dumps({"status": "ok", "version": version}).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                         + str(len(payload)).encode() + b"\r\nConnection: close\r\n\r\n" + payload)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    try:
        url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        async with aiohttp.ClientSession() as session:
            client = api.BridgeClient(session, url, KEY)
            if version not in ("0.6.0", "1.0.0", "1.1.0"):
                with pytest.raises(api.BridgeError) as caught:
                    await client.health()
                assert KEY not in str(caught.value) and "0.6.0" not in str(caught.value)
            else:
                assert (await client.health())["version"] == version
    finally:
        server.close()
        await server.wait_closed()


def test_manifest_translations_and_pinned_core_source_contract():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "1.1.0"
    # Core 2026.11.1 config_entries.py:1648-1667 rejects all rediscovery
    # BEFORE the handler if this flag is true. The flow enforces one DOMAIN ID.
    assert manifest["single_config_entry"] is False
    assert manifest["after_dependencies"] == ["hassio", "telegram_bot"]
    assert not manifest.get("dependencies") and "discovery" not in manifest
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    assert strings == json.loads((COMPONENT / "translations/es.json").read_text(encoding="utf-8"))
    assert "0.6.0" not in json.dumps(strings)
    assert "data" not in strings["config"]["step"]["user"]
    for step in ("automatic", "select_app"):
        assert "api_key" not in strings["config"]["step"][step]["data"]
    source = ast.parse((COMPONENT / "config_flow.py").read_text(encoding="utf-8"))
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "MenuCompraConfigFlow")
    step = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_step_hassio")
    assert ast.unparse(step.args.args[1].annotation) == "HassioServiceInfo"

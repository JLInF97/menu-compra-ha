"""Compatibilidad del validador de estado; respuestas fixture explícitas, sin red."""
import asyncio

import pytest

from test_ha_support import pure_module


@pytest.mark.parametrize('version,valid', [('0.6.0',True),('1.0.0',True),('1.1.0',True),('9.0.0',False)])
def test_bridge_version_validator_for_staged_upgrade(version, valid):
    api = pure_module('api')
    class StatusFixture:
        async def _request(self, *args, **kwargs):
            return {'status':'ok', 'version':version}
    if valid:
        assert asyncio.run(api.BridgeClient.health(StatusFixture()))['version'] == version
    else:
        with pytest.raises(api.BridgeError):
            asyncio.run(api.BridgeClient.health(StatusFixture()))

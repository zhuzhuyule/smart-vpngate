"""Provider implementations for Smart VPNGate.

Each provider implements :class:`smart_vpngate.provider.Provider`. VPNGate is the
first concrete provider; :class:`FakeProvider` is an in-memory implementation
used for tests and demos (and by ``python -m smart_vpngate run --provider fake``).
"""

from __future__ import annotations

from .fake import FakeProvider
from .legacy import LegacyEngineConnector
from .vpngate import VPNGateProvider

__all__ = ["FakeProvider", "VPNGateProvider", "LegacyEngineConnector"]

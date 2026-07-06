"""Smart VPNGate — a free, policy-driven Smart Exit Manager.

This package implements the V2 architecture described in ``docs/DESIGN.md`` as
five independent layers::

    Discovery -> NodePool -> Policy -> Exit -> Dashboard

Each layer lives in its own module and obeys the design principles:

* Discovery only discovers, filters and caches (it never connects or selects).
* Policy owns every exit decision.
* Providers are thin (Connect / Disconnect / Status only).
* Exactly one active exit exists at any time.

The package is intentionally decoupled from the legacy ``vpngate_manager``
monolith so the layers can be built and tested in isolation.
"""

from __future__ import annotations

__version__ = "2.0.0-dev"

from .models import Node
from .provider import Provider, ProviderStatus

__all__ = ["Node", "Provider", "ProviderStatus", "__version__"]

"""Dispatch only trusted adapters, using the public file-backed contract."""
from __future__ import annotations

from .capabilities import CapabilityCatalog


class CapabilityExecutor:
    def __init__(self, root, adapter, goal):
        self.catalog = CapabilityCatalog(root)
        self.adapter, self.goal = adapter, goal

    def __call__(self, name, params, *, progress, cancelled, timeout, directory):
        entry = self.catalog.read(name)
        params = self.catalog.parameters(name, params)
        if cancelled():
            return {'outcome': 'cancelled', 'verified': False}
        if not self.adapter.computer.live:
            return {'outcome': 'unknown', 'verified': False, 'message': 'Simulation cannot execute game capabilities'}
        if entry['domain'] != 'hololive_dreams':
            raise ValueError('No trusted adapter registered for domain: ' + entry['domain'])
        from modular_agent.domains.hololive_dreams.capability_adapters import execute
        previous_cancelled = getattr(self.adapter.computer, 'cancelled', None)
        self.adapter.computer.cancelled = cancelled
        try:
            return execute(self.adapter, self.goal, name.split('.')[1], params,
                           progress=progress, cancelled=cancelled, timeout=timeout, directory=directory)
        finally:
            try: self.adapter.computer.release_all()
            finally:
                if previous_cancelled is None: del self.adapter.computer.cancelled
                else: self.adapter.computer.cancelled = previous_cancelled

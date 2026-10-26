"""Compatibility imports for the Holodori daily workflow.

Game-specific implementation lives in modular_agent.domains.hololive_dreams.
Generic transitions and input delivery live in agent.interaction/ui_actions.
"""
from modular_agent.domains.hololive_dreams.daily_tasks import (
    DailyTasks, NOTICES, WORK, TEMPLATES, validate_config,
)

__all__ = ['DailyTasks', 'NOTICES', 'WORK', 'TEMPLATES', 'validate_config']

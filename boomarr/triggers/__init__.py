"""Trigger sources for the watch subsystem.

Defines the abstract interface for producing scan events and provides
the default schedule-based implementation.
"""

from boomarr.triggers.base import TriggerSource
from boomarr.triggers.schedule import ScheduleTrigger

__all__ = ["ScheduleTrigger", "TriggerSource"]

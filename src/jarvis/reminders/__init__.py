"""Reminder subsystem: local-first, time-triggered spoken + tray reminders.

Public surface is built up as the modules land. See ``reminders.spec.md`` for
the design contract (poll-loop firing, dateparser+LLM parsing, core/desktop
decoupling, fail-open).
"""

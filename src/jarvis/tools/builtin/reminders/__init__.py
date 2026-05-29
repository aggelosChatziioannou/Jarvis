"""Reminder tools: createReminder / listReminders / cancelReminder / snoozeReminder.

Each exposes a single optional ``text`` property so the planner fast-path can
dispatch it without an LLM resolver call, and returns raw data (no LLM
formatting) per the tool contract.
"""

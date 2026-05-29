"""Jarvis Vision & Screen Interaction Engine.

Modular package that lets Jarvis *see* the screen (describe / read / locate)
and, with safety guards, *act* on it (click / type / scroll). The package is
deliberately self-contained: it never calls the LLM for prose and never drives
TTS. The thin Tools in ``jarvis.tools.builtin.vision`` expose it to the
assistant and return raw data; the unified system prompt does all formatting.

See ``vision.spec.md`` for the full contract.
"""

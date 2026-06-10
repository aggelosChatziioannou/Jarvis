"""
Jarvis Desktop App - System Tray Application

A cross-platform system tray app for controlling the Jarvis voice assistant.
Supports Windows, Ubuntu (Linux), and macOS.
"""

from __future__ import annotations
import sys
import os

# Fix OpenBLAS threading crash in bundled apps
# Must be set before numpy is imported (via faster-whisper, etc.)
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')

# Keep QtWebEngine windows from blanking / reloading on move.
#
# The translucent, always-on-top floating HUD is a layered window. While it
# is dragged, Chromium's native window-occlusion calculator on Windows can
# briefly flag it as occluded, discard its compositor surface, and reload the
# page from scratch when it reappears (the HUD's boot sequence restarts).
# Disabling CalculateNativeWinOcclusion stops that discard. It does NOT turn
# off GPU acceleration, so the dashboard's WebGL dollhouse is unaffected.
# Must be set before QtWebEngine initialises (i.e. before importing app).
_occlusion_flag = '--disable-features=CalculateNativeWinOcclusion'
_existing_flags = os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', '')
if 'CalculateNativeWinOcclusion' not in _existing_flags:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = (
        f'{_existing_flags} {_occlusion_flag}'.strip()
    )

# Re-export main for entry point
from desktop_app.app import main

# Re-export commonly used components for backwards compatibility
from desktop_app.app import (
    get_crash_paths,
    check_previous_crash,
    mark_session_started,
    mark_session_clean_exit,
    setup_crash_logging,
    show_crash_report_dialog,
    check_model_support,
    show_unsupported_model_dialog,
    acquire_single_instance_lock,
    JarvisSystemTray,
    LogViewerWindow,
    MemoryViewerWindow,
    LogSignals,
)

__all__ = [
    'main',
    'get_crash_paths',
    'check_previous_crash',
    'mark_session_started',
    'mark_session_clean_exit',
    'setup_crash_logging',
    'show_crash_report_dialog',
    'check_model_support',
    'show_unsupported_model_dialog',
    'acquire_single_instance_lock',
    'JarvisSystemTray',
    'LogViewerWindow',
    'MemoryViewerWindow',
    'LogSignals',
]

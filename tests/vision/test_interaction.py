"""Behaviour tests for vision.interaction — the pyautogui input layer.

The pyautogui backend is injected so tests assert the exact calls made
(coordinates, button, text, scroll amount) without moving the real mouse.
"""

from jarvis.vision.interaction import Interactor


class _FakeBackend:
    FAILSAFE = True
    PAUSE = 0.0

    def __init__(self):
        self.calls = []

    def moveTo(self, x, y, duration=0.0):
        self.calls.append(("moveTo", x, y, duration))

    def click(self, x=None, y=None, button="left", clicks=1):
        self.calls.append(("click", x, y, button, clicks))

    def typewrite(self, text, interval=0.0):
        self.calls.append(("typewrite", text, interval))

    def scroll(self, amount, x=None, y=None):
        self.calls.append(("scroll", amount, x, y))


def test_click_passes_absolute_coordinates():
    be = _FakeBackend()
    Interactor(backend=be).click(1450, 450)
    assert be.calls == [("click", 1450, 450, "left", 1)]


def test_click_supports_button_and_count():
    be = _FakeBackend()
    Interactor(backend=be).click(10, 20, button="right", clicks=2)
    assert be.calls == [("click", 10, 20, "right", 2)]


def test_move_to():
    be = _FakeBackend()
    Interactor(backend=be).move_to(100, 200)
    assert be.calls[0][:3] == ("moveTo", 100, 200)


def test_type_text():
    be = _FakeBackend()
    Interactor(backend=be).type_text("hello world", interval=0.02)
    assert be.calls == [("typewrite", "hello world", 0.02)]


def test_scroll_at_point():
    be = _FakeBackend()
    Interactor(backend=be).scroll(-3, x=500, y=400)
    assert be.calls == [("scroll", -3, 500, 400)]


def test_scroll_without_point():
    be = _FakeBackend()
    Interactor(backend=be).scroll(5)
    assert be.calls == [("scroll", 5, None, None)]

"""Built-in vision tools — thin wrappers over the VisionEngine that return raw
data. The unified system prompt formats everything; these tools never produce
prose or drive TTS.
"""

from .see_screen import SeeScreenTool
from .read_screen import ReadScreenTool
from .locate_on_screen import LocateOnScreenTool
from .click_screen import ClickScreenTool
from .type_on_screen import TypeOnScreenTool
from .scroll_screen import ScrollScreenTool
from .confirm_screen_action import ConfirmScreenActionTool

__all__ = [
    "SeeScreenTool",
    "ReadScreenTool",
    "LocateOnScreenTool",
    "ClickScreenTool",
    "TypeOnScreenTool",
    "ScrollScreenTool",
    "ConfirmScreenActionTool",
]

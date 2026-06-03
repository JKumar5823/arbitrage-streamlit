"""Cursor control and screen capture.

Thin wrapper around ``pyautogui`` (cursor) and ``mss`` (fast screenshots).
All third-party imports are lazy so this module loads even on a headless box;
calling a function without a display raises a clear, actionable error.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from PIL import Image


class NoDisplayError(RuntimeError):
    """Raised when cursor/screen actions are attempted without a display."""


def _pyautogui():
    try:
        import pyautogui  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - depends on local env
        raise NoDisplayError(
            "pyautogui could not be loaded. Run this on your laptop (not a "
            "headless server) with a display attached. On Linux you also need "
            "an X server and the python3-tk / scrot packages.\n"
            f"Original error: {exc}"
        ) from exc
    # Safety: slamming the mouse into a screen corner aborts a runaway script.
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    return pyautogui


@dataclass
class Region:
    """A screen rectangle in pixels."""

    left: int
    top: int
    width: int
    height: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.width, self.height)

    @property
    def is_valid(self) -> bool:
        return self.width > 0 and self.height > 0


# --- cursor control ---------------------------------------------------------

def screen_size() -> tuple[int, int]:
    pg = _pyautogui()
    size = pg.size()
    return int(size.width), int(size.height)


def get_position() -> tuple[int, int]:
    pg = _pyautogui()
    pos = pg.position()
    return int(pos.x), int(pos.y)


def move_to(x: int, y: int, duration: float = 0.4) -> tuple[int, int]:
    pg = _pyautogui()
    pg.moveTo(x, y, duration=duration)
    return get_position()


def click(
    x: Optional[int] = None,
    y: Optional[int] = None,
    button: str = "left",
    clicks: int = 1,
    interval: float = 0.1,
) -> tuple[int, int]:
    pg = _pyautogui()
    if x is not None and y is not None:
        pg.click(x=x, y=y, clicks=clicks, interval=interval, button=button)
    else:
        pg.click(clicks=clicks, interval=interval, button=button)
    return get_position()


def scroll(amount: int, x: Optional[int] = None, y: Optional[int] = None) -> None:
    """Scroll vertically. Positive scrolls up, negative scrolls down."""
    pg = _pyautogui()
    pg.scroll(amount, x=x, y=y)


def hotkey(*keys: str) -> None:
    """Press a key combination, e.g. hotkey('ctrl', 'tab')."""
    pg = _pyautogui()
    pg.hotkey(*keys)


def countdown(seconds: int, on_tick=None) -> None:
    """Block for ``seconds``, calling ``on_tick(remaining)`` each second.

    Gives you time to bring the PitchBook window to the foreground before a
    capture fires.
    """
    for remaining in range(seconds, 0, -1):
        if on_tick is not None:
            on_tick(remaining)
        time.sleep(1)


# --- screen capture ---------------------------------------------------------

def capture(region: Optional[Region] = None) -> Image.Image:
    """Capture the full screen (or a sub-region) and return a PIL image."""
    try:
        import mss  # noqa: PLC0415
    except Exception:
        # Fall back to pyautogui's screenshot if mss is unavailable.
        pg = _pyautogui()
        shot = pg.screenshot(region=region.as_tuple() if region else None)
        return shot.convert("RGB")

    with mss.mss() as sct:
        if region is not None and region.is_valid:
            box = {
                "left": region.left,
                "top": region.top,
                "width": region.width,
                "height": region.height,
            }
        else:
            box = sct.monitors[1]  # primary monitor, excludes virtual union
        raw = sct.grab(box)
        return Image.frombytes("RGB", raw.size, raw.rgb)


def capture_to_file(path: str, region: Optional[Region] = None) -> str:
    img = capture(region)
    img.save(path)
    return path

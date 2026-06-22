from __future__ import annotations

import time

from pynput.mouse import Button, Controller


class MouseController:
    def __init__(self) -> None:
        self.mouse = Controller()

    def click(self, x: int, y: int, hold_seconds: float = 0.05) -> None:
        self.mouse.position = (x, y)
        self.mouse.press(Button.left)
        time.sleep(hold_seconds)
        self.mouse.release(Button.left)

    def move_to(self, x: int, y: int) -> None:
        self.mouse.position = (x, y)

    def hold_click(self, x: int, y: int, hold_seconds: float) -> None:
        self.mouse.position = (x, y)
        self.mouse.press(Button.left)
        time.sleep(hold_seconds)
        self.mouse.release(Button.left)

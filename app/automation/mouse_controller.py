from __future__ import annotations

import time

from pynput.mouse import Button, Controller


class MouseController:
    def __init__(self) -> None:
        self.mouse = Controller()
        self.left_pressed = False

    def click(self, x: int, y: int, hold_seconds: float = 0.05, before_press=None) -> None:
        self.mouse.position = (x, y)
        if before_press:
            before_press()
        self.mouse.press(Button.left)
        self.left_pressed = True
        time.sleep(hold_seconds)
        self.mouse.release(Button.left)
        self.left_pressed = False

    def move_to(self, x: int, y: int) -> None:
        self.mouse.position = (x, y)

    def hold_click(self, x: int, y: int, hold_seconds: float, before_press=None) -> None:
        self.mouse.position = (x, y)
        if before_press:
            before_press()
        self.mouse.press(Button.left)
        self.left_pressed = True
        time.sleep(hold_seconds)
        self.mouse.release(Button.left)
        self.left_pressed = False

    def release_left(self) -> None:
        try:
            self.mouse.release(Button.left)
        finally:
            self.left_pressed = False

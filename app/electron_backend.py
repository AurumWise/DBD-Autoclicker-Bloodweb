from __future__ import annotations

import base64
import json
import logging
import math
import queue
import shutil
import sys
import threading
import time
import tkinter as tk
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
from pynput import keyboard

from app.automation.mouse_controller import MouseController
from app.capture.screenshot import ScreenshotService
from app.data.search_template_repository import SearchTemplateRepository
from app.grid.geometry import GridTemplateRepository, RING_SPECS, build_rois
from app.logging_setup import configure_logging
from app.models import GridTemplate, NodeROI
from app.safety.center_anchor import (
    CENTER_ANCHOR_DEFAULT_THRESHOLD,
    CENTER_CONFIRMED,
    CENTER_NOT_CONFIRMED,
    CENTER_RECHECKING,
    CENTER_UNCONFIGURED,
    SAFETY_CONSENT_FILE,
    SAFETY_TERMS_VERSION,
    CenterAnchorMatcher,
    CenterAnchorRepository,
    CenterConfirmationMachine,
)
from app.runtime_config import CAPTURE_BOX_ROI_RATIO, SCREENSHOT_MOUSE_PARKING_POSITION
from app.version import APP_NAME_EN, APP_VERSION
from app.vision.image_io import imread_unicode
from app.vision.snippet_matcher import NORMALIZATION_CROP_RATIO, SnippetMatcher


def resolve_runtime_root() -> Path:
    cwd = Path.cwd().resolve()
    if (cwd / "package.json").exists() and (cwd / "db").is_dir():
        return cwd
    return Path(__file__).resolve().parents[1]


ROOT = resolve_runtime_root()
UI_STATE_PATH = ROOT / "db" / "ui_state.json"
LOG_PATH = ROOT / "logs" / "app.log"
SAFETY_CONSENT_PATH = ROOT / "db" / SAFETY_CONSENT_FILE
MATCH_MARGIN_THRESHOLD = 0.0
SCREENSHOT_AFTER_MOUSE_MOVE_DELAY_SECONDS = 0.2
DETAILED_MATCH_MIN_SCORE = 0.75
DETAILED_MATCH_MAX_SCORE = 0.85
CENTER_CHECK_INTERVAL_SECONDS = 1.0
CENTER_RECHECK_DELAY_SECONDS = 0.15
CENTER_UI_LOG_MARKERS = (
    "center_check",
    "center_recheck",
    "Center setup",
    "Center anchor",
    "center_not_confirmed",
    "Центр Bloodweb",
    "Перепроверка центра",
)


class RestartAutoCycle(Exception):
    pass


logger = logging.getLogger(__name__)


def _safe_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


class ElectronBackend:
    def __init__(self) -> None:
        configure_logging(ROOT)

        self.root = tk.Tk()
        self.root.withdraw()

        self.template_repo = GridTemplateRepository(ROOT)
        self.search_template_repo = SearchTemplateRepository(ROOT)
        self.capture_service = ScreenshotService(ROOT)
        self.mouse_controller = MouseController()
        self.matcher = SnippetMatcher()
        self.center_anchor_repo = CenterAnchorRepository(ROOT)
        self.center_anchor_matcher = CenterAnchorMatcher(self.matcher)

        self.template = self.load_or_create_grid_template()
        self.ui_state = self.load_ui_state()
        self.search_data = self.search_template_repo.load()
        self.enforce_single_owner_items()
        self.enrich_search_item_sizes()

        self.current_template_name = str(self.ui_state.get("current_template_name") or "")
        if not self.current_template():
            templates = self.template_records()
            self.current_template_name = templates[0]["name"] if templates else ""

        self.status = "Готов"
        self.status_message = "Готово"
        self.grid_message = "Сетка сохранена"
        self.grid_visible = False
        self.adding_capture = False
        self.grid_drag_data: tuple[float, float, float, float] | None = None
        self.grid_resize_data: tuple[int, float, float] | None = None
        self.capture_drag_data: tuple[float, float, float, float] | None = None
        self.capture_exclusion_rect: tuple[int, int, int, int] | None = None
        self.electron_window_rect: tuple[int, int, int, int] | None = None

        self.queue_items: list[dict] = []
        self.next_click: dict | None = None
        self.auto_thread: threading.Thread | None = None
        self.mouse_monitor_thread: threading.Thread | None = None
        self.expected_mouse_position: tuple[int, int] | None = None
        self.mouse_monitor_paused_until = 0.0
        self.programmatic_mouse_action_active = False
        self.mouse_stop_notified = False
        self.stop_requested = False
        self.restart_auto_cycle_requested = False
        self.stop_lock = threading.RLock()
        self.safety_lock = threading.RLock()
        self.clicks_allowed_event = threading.Event()
        self.center_anchor = self.center_anchor_repo.load()
        self.center_machine = CenterConfirmationMachine(configured=self.center_anchor is not None)
        self.center_last_score: float | None = None
        self.center_last_message = "Центр Bloodweb не настроен" if self.center_anchor is None else "Центр Bloodweb не подтверждён"
        self.center_check_thread: threading.Thread | None = None
        self.center_check_stop = threading.Event()
        self.center_setup_active = False
        self.center_hover_roi: NodeROI | None = None
        self.center_marker_drag_data: tuple[float, float, float, float] | None = None
        self.center_resize_data: tuple[float, float, float, float, float] | None = None
        self.center_marker_x = float(self.template.center_x)
        self.center_marker_y = float(self.template.center_y)
        self.center_confirm_rect: tuple[float, float, float, float] | None = None
        self.center_cancel_rect: tuple[float, float, float, float] | None = None
        self.center_reset_rect: tuple[float, float, float, float] | None = None
        self.grid_reset_rect: tuple[float, float, float, float] | None = None
        self.pending_center_anchor: dict | None = None
        self.pending_reference_capture: dict | None = None
        self.emergency_stop_reason: str | None = None
        self.safety_consent = self.load_safety_consent()
        self.keyboard_listener = None
        self.screenshot_request_lock = threading.Event()
        self.screenshot_result = None
        self.command_queue: queue.Queue[tuple[int | None, str, dict]] = queue.Queue()
        self.log_lines: list[str] = []
        self.last_error: str | None = None
        self.shutting_down = False

        self.overlay = tk.Toplevel(self.root)
        self.setup_overlay()
        self.overlay.withdraw()
        self.set_capture_size_from_grid()
        self.add_log("Electron backend ready")
        self.start_center_monitor()
        self.start_hotkey_listener()

    def load_or_create_grid_template(self) -> GridTemplate:
        templates = self.template_repo.list_templates()
        if templates:
            return templates[0]

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        template = GridTemplate(
            name="default_bloodweb_grid",
            screenshot="",
            image_size=[screen_w, screen_h],
            center_x=screen_w * 0.35,
            center_y=screen_h * 0.53,
            ring1_radius=130.0,
            ring2_radius=260.0,
            ring3_radius=390.0,
            rotation_deg=0.0,
            roi_size=90.0,
        )
        self.save_grid_template(template)
        return template

    def load_ui_state(self) -> dict:
        default = {
            "tool_x": 80,
            "tool_y": 80,
            "capture_x": 80.0,
            "capture_y": 80.0,
            "threshold": 0.80,
            "pre_click_delay_seconds": 0.35,
            "delay_between_clicks_seconds": 3.0,
            "click_hold_seconds": 0.05,
            "center_hold_seconds": 1.0,
            "after_center_delay_seconds": 3.0,
            "center_lost_timeout_seconds": 30.0,
            "screenshot_settle_seconds": SCREENSHOT_AFTER_MOUSE_MOVE_DELAY_SECONDS,
            "mouse_check_interval_seconds": 0.03,
            "mouse_move_tolerance_pixels": 45.0,
            "detailed_match_min_score": DETAILED_MATCH_MIN_SCORE,
            "detailed_match_max_score": DETAILED_MATCH_MAX_SCORE,
            "center_anchor_confidence_threshold": CENTER_ANCHOR_DEFAULT_THRESHOLD,
            "always_on_top": False,
            "current_template_name": "",
            "ui_language": "ru",
        }
        if not UI_STATE_PATH.exists():
            return default
        try:
            data = json.loads(UI_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
        result = default | data
        for key in (
            "capture_x",
            "capture_y",
            "threshold",
            "pre_click_delay_seconds",
            "delay_between_clicks_seconds",
            "click_hold_seconds",
            "center_hold_seconds",
            "after_center_delay_seconds",
            "center_lost_timeout_seconds",
            "screenshot_settle_seconds",
            "mouse_check_interval_seconds",
            "mouse_move_tolerance_pixels",
            "detailed_match_min_score",
            "detailed_match_max_score",
            "center_anchor_confidence_threshold",
        ):
            result[key] = float(result[key])
        result["tool_x"] = int(result.get("tool_x", default["tool_x"]))
        result["tool_y"] = int(result.get("tool_y", default["tool_y"]))
        result["always_on_top"] = bool(result.get("always_on_top", False))
        language = str(result.get("ui_language") or "ru").lower()
        result["ui_language"] = language if language in {"ru", "en"} else "ru"
        result.setdefault("matcher_version", 2)
        return result

    def save_ui_state(self) -> None:
        self.ui_state["current_template_name"] = self.current_template_name
        UI_STATE_PATH.write_text(json.dumps(self.ui_state, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_safety_consent(self) -> dict:
        default = {"accepted": False, "terms_version": 0, "accepted_at": ""}
        if not SAFETY_CONSENT_PATH.exists():
            return default
        try:
            data = json.loads(SAFETY_CONSENT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
        return default | data

    def safety_consent_accepted(self) -> bool:
        return bool(self.safety_consent.get("accepted")) and int(self.safety_consent.get("terms_version", 0)) == SAFETY_TERMS_VERSION

    def accept_safety_consent(self) -> None:
        SAFETY_CONSENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.safety_consent = {
            "accepted": True,
            "terms_version": SAFETY_TERMS_VERSION,
            "accepted_at": datetime.now().isoformat(),
        }
        SAFETY_CONSENT_PATH.write_text(json.dumps(self.safety_consent, ensure_ascii=False, indent=2), encoding="utf-8")
        self.status_message = "Согласие сохранено"
        self.add_log("Safety consent accepted")

    def setup_overlay(self) -> None:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.attributes("-transparentcolor", "#ff00ff")
        self.overlay.geometry(f"{screen_w}x{screen_h}+0+0")
        self.canvas = tk.Canvas(self.overlay, width=screen_w, height=screen_h, bg="#ff00ff", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self.on_left_press)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<Motion>", self.on_overlay_motion)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.overlay.bind("<Escape>", lambda _e: self.cancel_overlay_mode())

    def run(self) -> None:
        threading.Thread(target=self.stdin_loop, daemon=True).start()
        self.root.after(50, self.process_commands)
        self.root.mainloop()

    def stdin_loop(self) -> None:
        try:
            for raw_line in sys.stdin.buffer:
                try:
                    line = raw_line.decode("utf-8")
                    message = json.loads(line)
                    self.command_queue.put((message.get("id"), str(message.get("command", "")), message.get("payload") or {}))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    self.send({"type": "error", "error": f"Bad JSON: {exc}"})
        finally:
            if not self.shutting_down:
                try:
                    self.root.after(0, self.shutdown)
                except RuntimeError:
                    pass

    def process_commands(self) -> None:
        while True:
            try:
                message_id, command, payload = self.command_queue.get_nowait()
            except queue.Empty:
                break
            try:
                result = self.handle_command(command, payload)
                if message_id is not None:
                    self.send({"type": "response", "id": message_id, "ok": True, "result": result})
            except Exception as exc:
                logger.exception("Electron command failed: %s", command)
                self.last_error = str(exc)
                self.status = "Ошибка"
                self.status_message = str(exc)
                if message_id is not None:
                    self.send({"type": "response", "id": message_id, "ok": False, "error": str(exc), "state": self.state()})
        if not self.shutting_down:
            self.root.after(50, self.process_commands)

    def send(self, payload: dict) -> None:
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()

    def push_state(self) -> None:
        self.send({"type": "state", "state": self.state()})

    def handle_command(self, command: str, payload: dict) -> dict:
        if command == "shutdown":
            state = self.state()
            self.root.after(0, self.shutdown)
            return state
        if command == "getState":
            return self.state()
        if command == "setAlwaysOnTop":
            self.ui_state["always_on_top"] = bool(payload.get("value"))
            self.save_ui_state()
            return self.state()
        if command == "updateWindowBounds":
            x = int(payload.get("x", 0))
            y = int(payload.get("y", 0))
            width = int(payload.get("width", 0))
            height = int(payload.get("height", 0))
            self.electron_window_rect = (x, y, x + width, y + height)
            return self.state()
        if command == "toggleGrid":
            self.toggle_grid()
            return self.state()
        if command == "beginCenterSetup":
            self.begin_center_setup()
            return self.state()
        if command == "saveCenterAnchor":
            self.save_pending_center_anchor(str(payload.get("name", "")))
            return self.state()
        if command == "cancelCenterAnchor":
            self.cancel_pending_center_anchor()
            return self.state()
        if command == "acceptSafetyConsent":
            self.accept_safety_consent()
            return self.state()
        if command == "setTemplate":
            self.set_current_template(str(payload.get("name", "")))
            return self.state()
        if command == "testQueue":
            self.test_click_queue()
            return self.state()
        if command == "start":
            self.start_auto()
            return self.state()
        if command == "stop":
            self.stop_auto()
            return self.state()
        if command == "saveSettings":
            self.apply_settings(payload)
            return self.state()
        if command == "setLanguage":
            language = str(payload.get("language") or "ru").lower()
            self.ui_state["ui_language"] = language if language in {"ru", "en"} else "ru"
            self.save_ui_state()
            return self.state()
        if command == "moveItem":
            self.move_item(str(payload.get("source")), str(payload.get("target")), int(payload.get("index", -1)))
            return self.state()
        if command == "reorderItem":
            self.reorder_item(str(payload.get("list")), int(payload.get("index", -1)), int(payload.get("direction", 0)))
            return self.state()
        if command == "renameItem":
            self.rename_item(str(payload.get("list")), int(payload.get("index", -1)), str(payload.get("label", "")))
            return self.state()
        if command == "removeItem":
            self.remove_item(str(payload.get("list")), int(payload.get("index", -1)))
            return self.state()
        if command == "createTemplate":
            self.create_template(str(payload.get("name", "")))
            return self.state()
        if command == "renameTemplate":
            self.rename_template(str(payload.get("name", "")))
            return self.state()
        if command == "duplicateTemplate":
            self.duplicate_template(str(payload.get("name", "")))
            return self.state()
        if command == "deleteTemplate":
            self.delete_template(str(payload.get("name", "")) or None)
            return self.state()
        if command == "openAddCapture":
            self.open_add_capture()
            return self.state()
        if command == "closeAddCapture":
            self.close_add_capture()
            return self.state()
        if command == "captureReference":
            self.save_pending_reference_capture(str(payload.get("label", "")))
            return self.state()
        if command == "cancelReferenceCapture":
            self.cancel_reference_capture()
            return self.state()
        raise ValueError(f"Unknown command: {command}")

    def shutdown(self) -> None:
        if self.shutting_down:
            return
        self.shutting_down = True
        self.stop_requested = True
        self.center_check_stop.set()
        self.clicks_allowed_event.clear()
        try:
            self.mouse_controller.release_left()
        except Exception:
            logger.exception("Unable to release mouse button during shutdown")
        if self.keyboard_listener is not None:
            try:
                self.keyboard_listener.stop()
            except Exception:
                logger.exception("Unable to stop keyboard listener during shutdown")
            self.keyboard_listener = None
        try:
            self.overlay.withdraw()
        except Exception:
            logger.exception("Unable to hide overlay during shutdown")
        try:
            self.root.after(150, self.finish_shutdown)
        except RuntimeError:
            self.finish_shutdown()

    def finish_shutdown(self) -> None:
        try:
            self.overlay.destroy()
        except Exception:
            logger.exception("Unable to destroy overlay during shutdown")
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            logger.exception("Unable to destroy root during shutdown")

    def state(self) -> dict:
        template = self.current_template()
        return {
            "app_name": APP_NAME_EN,
            "app_version": APP_VERSION,
            "status": self.status,
            "status_message": self.status_message,
            "grid_visible": self.grid_visible,
            "grid_message": self.grid_message,
            "adding_capture": self.adding_capture,
            "center": self.center_state(),
            "reference_capture": self.reference_capture_state(),
            "always_on_top": bool(self.ui_state.get("always_on_top", False)),
            "current_template": self.current_template_name,
            "templates": self.template_records(),
            "priority_items": [self.public_item(item, index, "Приоритет") for index, item in enumerate(self.search_data.get("priority_items", []), start=1)],
            "template_items": [self.public_item(item, index, "Шаблон") for index, item in enumerate((template or {}).get("items", []), start=1)],
            "queue": self.queue_items,
            "next_click": self.next_click,
            "is_running": bool(self.auto_thread and self.auto_thread.is_alive() and not self.stop_requested),
            "settings": self.settings_state(),
            "logs": self.read_log_lines(),
            "last_error": self.last_error,
            "emergency_stop_reason": self.emergency_stop_reason,
            "safety_terms_version": SAFETY_TERMS_VERSION,
            "safety_consent_accepted": self.safety_consent_accepted(),
            "safety_consent_required": not self.safety_consent_accepted(),
        }

    def center_state(self) -> dict:
        anchor = self.center_anchor
        return {
            "state": self.center_machine.state,
            "configured": anchor is not None,
            "name": anchor.name if anchor else "",
            "node_id": anchor.node_id if anchor else "",
            "score": self.center_last_score,
            "threshold": float(self.ui_state.get("center_anchor_confidence_threshold", CENTER_ANCHOR_DEFAULT_THRESHOLD)),
            "message": self.center_last_message,
            "clicks_allowed": self.clicks_allowed_event.is_set(),
            "setup_active": self.center_setup_active,
            "pending": self.pending_center_anchor is not None,
            "pending_thumbnail": (self.pending_center_anchor or {}).get("thumbnail"),
        }

    def reference_capture_state(self) -> dict:
        return {
            "active": self.adding_capture,
            "pending": self.pending_reference_capture is not None,
            "pending_thumbnail": (self.pending_reference_capture or {}).get("thumbnail"),
        }

    def template_records(self) -> list[dict]:
        result = []
        for section, key in (("killer", "killer_templates"), ("survivor", "survivor_templates")):
            for index, template in enumerate(self.search_data.get(key, [])):
                result.append({"section": section, "index": index, "name": template.get("name", "template")})
        return result

    def current_template(self) -> dict | None:
        for record in self.template_records():
            if record["name"] == self.current_template_name:
                key = "killer_templates" if record["section"] == "killer" else "survivor_templates"
                templates = self.search_data.get(key, [])
                if 0 <= record["index"] < len(templates):
                    return templates[record["index"]]
        return None

    def current_template_key_index(self) -> tuple[str, int] | None:
        for record in self.template_records():
            if record["name"] == self.current_template_name:
                key = "killer_templates" if record["section"] == "killer" else "survivor_templates"
                return key, int(record["index"])
        return None

    def set_current_template(self, name: str) -> None:
        if not any(record["name"] == name for record in self.template_records()):
            raise ValueError("Шаблон не найден")
        self.current_template_name = name
        self.save_ui_state()
        self.status = "Готов"
        self.status_message = f"Выбран шаблон: {name}"
        self.add_log(f"Template selected: {name}")

    def public_item(self, item: dict, index: int, kind: str) -> dict:
        return {
            "id": item.get("id"),
            "label": item.get("label", "template"),
            "image_path": item.get("image_path"),
            "thumbnail": self.thumbnail_data_url(item.get("image_path")),
            "position": index,
            "subtitle": f"{kind} {index}",
        }

    def thumbnail_data_url(self, image_path: str | None, size: int = 40) -> str | None:
        if not image_path:
            return None
        image = imread_unicode(Path(image_path), cv2.IMREAD_UNCHANGED)
        if image is None:
            return None
        if image.ndim == 3 and image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        elif image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        resized = cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".png", resized)
        if not ok:
            return None
        return "data:image/png;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")

    def settings_state(self) -> dict:
        keys = (
            "threshold",
            "detailed_match_min_score",
            "detailed_match_max_score",
            "center_anchor_confidence_threshold",
            "pre_click_delay_seconds",
            "delay_between_clicks_seconds",
            "click_hold_seconds",
            "center_hold_seconds",
            "after_center_delay_seconds",
            "center_lost_timeout_seconds",
            "screenshot_settle_seconds",
            "mouse_check_interval_seconds",
            "mouse_move_tolerance_pixels",
            "always_on_top",
            "ui_language",
        )
        return {key: self.ui_state.get(key) for key in keys}

    def apply_settings(self, payload: dict) -> None:
        settings = payload.get("settings") or payload
        min_detail = _safe_float(settings.get("detailed_match_min_score"), DETAILED_MATCH_MIN_SCORE, 0.0, 1.0)
        max_detail = _safe_float(settings.get("detailed_match_max_score"), DETAILED_MATCH_MAX_SCORE, 0.0, 1.0)
        if min_detail > max_detail:
            raise ValueError("Минимум детальной проверки больше максимума")
        self.ui_state["threshold"] = _safe_float(settings.get("threshold"), 0.80, 0.0, 1.0)
        self.ui_state["detailed_match_min_score"] = min_detail
        self.ui_state["detailed_match_max_score"] = max_detail
        self.ui_state["center_anchor_confidence_threshold"] = _safe_float(
            settings.get("center_anchor_confidence_threshold"),
            CENTER_ANCHOR_DEFAULT_THRESHOLD,
            0.0,
            1.0,
        )
        for key, default, minimum, maximum in (
            ("pre_click_delay_seconds", 0.35, 0.0, 5.0),
            ("delay_between_clicks_seconds", 3.0, 0.1, 30.0),
            ("click_hold_seconds", 0.05, 0.01, 2.0),
            ("center_hold_seconds", 1.0, 0.1, 10.0),
            ("after_center_delay_seconds", 3.0, 0.1, 30.0),
            ("center_lost_timeout_seconds", 30.0, 1.0, 300.0),
            ("screenshot_settle_seconds", SCREENSHOT_AFTER_MOUSE_MOVE_DELAY_SECONDS, 0.0, 2.0),
            ("mouse_check_interval_seconds", 0.03, 0.01, 0.50),
            ("mouse_move_tolerance_pixels", 45.0, 10.0, 200.0),
        ):
            self.ui_state[key] = _safe_float(settings.get(key), default, minimum, maximum)
        if "always_on_top" in settings:
            self.ui_state["always_on_top"] = bool(settings.get("always_on_top"))
        language = str(settings.get("ui_language") or self.ui_state.get("ui_language") or "ru").lower()
        self.ui_state["ui_language"] = language if language in {"ru", "en"} else "ru"
        self.save_ui_state()
        self.status_message = "Настройки сохранены"
        self.add_log("Settings saved")

    def enforce_single_owner_items(self) -> None:
        priority_ids = {item.get("id") for item in self.search_data.get("priority_items", [])}
        for key in ("killer_templates", "survivor_templates"):
            for template in self.search_data.get(key, []):
                template["items"] = [item for item in template.get("items", []) if item.get("id") not in priority_ids]

    def enrich_search_item_sizes(self) -> None:
        changed = False
        for item in self.iter_search_items():
            before = dict(item)
            self.search_template_repo.enrich_item_metadata_from_png(item)
            changed = changed or before != item
            image_path = item.get("image_path")
            resolved_path = self.search_template_repo.resolve_image_path(image_path)
            if resolved_path:
                self.matcher.ensure_template_variant_files(resolved_path, match_size=item.get("match_size"), crop_ratio=item.get("crop_ratio", NORMALIZATION_CROP_RATIO))
        if changed:
            self.save_search_data()

    def iter_search_items(self):
        yield from self.search_data.get("priority_items", [])
        for key in ("killer_templates", "survivor_templates"):
            for template in self.search_data.get(key, []):
                yield from template.get("items", [])

    def save_search_data(self) -> None:
        self.enforce_single_owner_items()
        self.search_template_repo.save(self.search_data)
        self.search_data = self.search_template_repo.load()

    def build_search_items(self) -> list[dict]:
        template = self.current_template()
        unique: dict[str, dict] = {}
        for item in self.search_data.get("priority_items", []):
            unique[item["id"]] = item
        if template:
            for item in template.get("items", []):
                if item["id"] not in unique:
                    unique[item["id"]] = item
        return list(unique.values())

    def move_item(self, source: str, target: str, index: int) -> None:
        source_items = self.items_for_list(source)
        target_items = self.items_for_list(target)
        if index < 0 or index >= len(source_items):
            raise ValueError("Элемент не выбран")
        item = source_items.pop(index)
        if any(existing.get("id") == item.get("id") for existing in target_items):
            source_items.insert(index, item)
            raise ValueError("Элемент уже есть в целевом списке")
        target_items.append(item)
        self.save_search_data()
        self.status_message = "Элемент перенесен"

    def reorder_item(self, list_name: str, index: int, direction: int) -> None:
        items = self.items_for_list(list_name)
        target = index + direction
        if index < 0 or index >= len(items) or target < 0 or target >= len(items):
            return
        items[index], items[target] = items[target], items[index]
        self.save_search_data()

    def rename_item(self, list_name: str, index: int, label: str) -> None:
        items = self.items_for_list(list_name)
        if index < 0 or index >= len(items):
            raise ValueError("Элемент не выбран")
        label = label.strip()
        if not label:
            raise ValueError("Название не может быть пустым")
        items[index]["label"] = label
        self.save_search_data()

    def remove_item(self, list_name: str, index: int) -> None:
        items = self.items_for_list(list_name)
        if index < 0 or index >= len(items):
            raise ValueError("Элемент не выбран")
        item = items.pop(index)
        self.save_search_data()
        self.delete_item_file_if_unreferenced(item)

    def items_for_list(self, list_name: str) -> list[dict]:
        if list_name == "priority":
            return self.search_data.setdefault("priority_items", [])
        if list_name == "template":
            template = self.current_template()
            if not template:
                raise ValueError("Шаблон не выбран")
            return template.setdefault("items", [])
        raise ValueError("Неизвестный список")

    def template_name_exists(self, name: str) -> bool:
        return any(record["name"] == name for record in self.template_records())

    def create_template(self, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Название шаблона не может быть пустым")
        if self.template_name_exists(name):
            raise ValueError("Шаблон с таким именем уже есть")
        self.search_data.setdefault("killer_templates", []).append({"name": name, "killer_id": None, "items": []})
        self.current_template_name = name
        self.save_search_data()
        self.save_ui_state()

    def rename_template(self, name: str) -> None:
        name = name.strip()
        template = self.current_template()
        if not template:
            raise ValueError("Шаблон не выбран")
        if not name:
            raise ValueError("Название шаблона не может быть пустым")
        if name != template.get("name") and self.template_name_exists(name):
            raise ValueError("Шаблон с таким именем уже есть")
        template["name"] = name
        self.current_template_name = name
        self.save_search_data()
        self.save_ui_state()

    def duplicate_template(self, name: str) -> None:
        name = name.strip()
        source = self.current_template()
        ref = self.current_template_key_index()
        if not source or not ref:
            raise ValueError("Шаблон не выбран")
        if not name:
            raise ValueError("Название шаблона не может быть пустым")
        if self.template_name_exists(name):
            raise ValueError("Шаблон с таким именем уже есть")
        cloned_items = [self.clone_template_item(item) for item in source.get("items", [])]
        key, _index = ref
        clone = {
            "name": name,
            "items": cloned_items,
        }
        if key == "killer_templates":
            clone["killer_id"] = source.get("killer_id")
        self.search_data.setdefault(key, []).append(clone)
        self.current_template_name = name
        self.save_search_data()
        self.save_ui_state()
        self.status_message = f"Шаблон создан: {name}"
        self.add_log(f"Template duplicated: {source.get('name')} -> {name}")

    def clone_template_item(self, item: dict) -> dict:
        source_path = Path(item.get("image_path", ""))
        if not source_path.exists():
            raise ValueError(f"PNG не найден: {source_path}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target_path = self.search_template_repo.image_dir / f"{timestamp}.png"
        shutil.copy2(source_path, target_path)
        cloned = dict(item)
        cloned["id"] = target_path.stem
        cloned["image_path"] = str(target_path)
        self.matcher.ensure_template_variant_files(
            target_path,
            match_size=cloned.get("match_size"),
            crop_ratio=cloned.get("crop_ratio", NORMALIZATION_CROP_RATIO),
            persist=True,
        )
        SearchTemplateRepository.enrich_item_metadata_from_png(cloned)
        return cloned

    def delete_template(self, name: str | None = None) -> None:
        ref = self.template_key_index_by_name(name or self.current_template_name)
        if not ref:
            raise ValueError("Шаблон не выбран")
        key, index = ref
        templates = self.search_data.get(key, [])
        removed = templates.pop(index)
        for item in removed.get("items", []):
            self.delete_item_file_if_unreferenced(item)
        if not self.template_records():
            self.search_data["killer_templates"] = [{"name": "default_killer", "killer_id": None, "items": []}]
            self.current_template_name = "default_killer"
        else:
            first = self.template_records()[0]
            self.current_template_name = first["name"]
        self.save_search_data()
        self.save_ui_state()
        self.status_message = f"Удален шаблон: {removed.get('name', '')}"
        self.add_log(f"Template deleted: {removed.get('name', '')}")

    def template_key_index_by_name(self, name: str) -> tuple[str, int] | None:
        for record in self.template_records():
            if record["name"] == name:
                key = "killer_templates" if record["section"] == "killer" else "survivor_templates"
                return key, int(record["index"])
        return None

    def begin_center_setup(self) -> None:
        self.adding_capture = False
        self.grid_visible = False
        self.center_setup_active = True
        self.center_hover_roi = None
        self.center_marker_drag_data = None
        if self.center_anchor and self.center_anchor.center_x is not None and self.center_anchor.center_y is not None:
            self.center_marker_x = float(self.center_anchor.center_x)
            self.center_marker_y = float(self.center_anchor.center_y)
        else:
            self.center_marker_x = float(self.template.center_x)
            self.center_marker_y = float(self.template.center_y)
        self.pending_center_anchor = None
        self.grid_message = "Выберите узел центра Bloodweb на сетке"
        self.grid_message = "Выберите узел для скрина"
        self.show_overlay_if_needed()
        self.redraw_overlay()
        self.add_log("Center setup started")

    def cancel_pending_center_anchor(self) -> None:
        self.pending_center_anchor = None
        self.center_setup_active = False
        self.center_hover_roi = None
        self.grid_message = "Сетка сохранена"
        self.hide_overlay_if_unused()
        self.redraw_overlay()
        self.status_message = "Настройка центра отменена"
        self.add_log("Center setup canceled")

    def save_pending_center_anchor(self, name: str) -> None:
        if not self.pending_center_anchor:
            raise ValueError("Нет нового снимка центра для сохранения")
        image = self.pending_center_anchor["image"]
        roi = self.pending_center_anchor["roi"]
        self.center_anchor = self.center_anchor_repo.save(name.strip() or "Центр Bloodweb", image, roi)
        self.center_machine.set_configured(True)
        self.clicks_allowed_event.clear()
        self.center_last_score = None
        self.center_last_message = "Центр Bloodweb сохранён, требуется подтверждение"
        self.pending_center_anchor = None
        self.center_setup_active = False
        self.center_hover_roi = None
        self.grid_message = "Сетка сохранена"
        self.hide_overlay_if_unused()
        self.redraw_overlay()
        self.status_message = "Центр Bloodweb сохранён"
        self.add_log(f"Center anchor saved: {self.center_anchor.node_id}")

    def capture_center_anchor_candidate(self, roi: NodeROI) -> None:
        self.canvas.delete("all")
        self.root.update_idletasks()
        try:
            image, _ = self.capture_service.capture_primary_monitor()
            crop = image[roi.y1 : roi.y2, roi.x1 : roi.x2]
            if crop.size == 0:
                raise ValueError("Пустой ROI центра")
            self.pending_center_anchor = {
                "image": crop.copy(),
                "roi": roi,
                "thumbnail": self.image_to_data_url(crop, size=96),
            }
            self.center_setup_active = False
            self.center_hover_roi = None
            self.grid_message = "Снимок центра готов к сохранению"
            self.add_log(f"Center anchor candidate captured: {roi.node_id}")
        finally:
            self.push_state()

    def save_center_anchor_from_marker(self) -> None:
        x = int(round(self.center_marker_x))
        y = int(round(self.center_marker_y))
        size = max(40, int(round(float(self.template.roi_size))))
        half = size // 2
        self.canvas.delete("all")
        self.root.update_idletasks()
        try:
            image, _ = self.capture_service.capture_primary_monitor()
            x1 = max(0, x - half)
            y1 = max(0, y - half)
            x2 = min(image.shape[1], x + half)
            y2 = min(image.shape[0], y + half)
            crop = image[y1:y2, x1:x2]
            if crop.size == 0:
                raise ValueError("Пустой снимок центра")
            self.template.center_x = float(x)
            self.template.center_y = float(y)
            self.save_grid_template(self.template)
            self.center_anchor = self.center_anchor_repo.save_point(crop.copy(), float(x), float(y), int(max(x2 - x1, y2 - y1)))
            self.center_machine.set_configured(True)
            self.clicks_allowed_event.clear()
            self.center_last_score = None
            self.center_last_message = "Центр Bloodweb сохранён, требуется подтверждение"
            self.center_setup_active = False
            self.center_marker_drag_data = None
            self.grid_message = "Центр сохранён. Паутина строится от выбранного центра."
            self.status_message = "Центр Bloodweb сохранён"
            self.add_log(f"Center anchor saved from point: x={x} y={y}")
        finally:
            self.hide_overlay_if_unused()
            self.redraw_overlay()
            self.push_state()

    def image_to_data_url(self, image, size: int = 40) -> str | None:
        if image is None or image.size == 0:
            return None
        if image.ndim == 3 and image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        elif image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        resized = cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".png", resized)
        if not ok:
            return None
        return "data:image/png;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")

    def open_add_capture(self) -> None:
        self.center_setup_active = False
        self.center_hover_roi = None
        self.pending_reference_capture = None
        self.adding_capture = True
        self.grid_visible = True
        self.grid_message = "Выберите узел для скрина"
        self.grid_message = "Выберите узел для скрина"
        self.show_overlay_if_needed()
        self.redraw_overlay()

    def close_add_capture(self) -> None:
        self.adding_capture = False
        self.center_hover_roi = None
        self.grid_visible = False
        self.grid_message = "Сетка показана" if self.grid_visible else "Сетка сохранена"
        self.hide_overlay_if_unused()
        self.redraw_overlay()

    def cancel_reference_capture(self) -> None:
        self.pending_reference_capture = None
        self.close_add_capture()
        self.status_message = "Добавление скрина отменено"

    def capture_reference_candidate(self, roi: NodeROI) -> None:
        overlay_was_needed = self.grid_visible or self.adding_capture or self.center_setup_active
        self.overlay.withdraw()
        self.root.update_idletasks()
        image, _ = self.capture_service.capture_primary_monitor()
        if overlay_was_needed:
            self.overlay.deiconify()
            self.overlay.lift()
            self.overlay.attributes("-topmost", True)
        crop = image[roi.y1 : roi.y2, roi.x1 : roi.x2]
        if crop.size == 0:
            raise ValueError("Пустая область скрина")
        self.pending_reference_capture = {
            "image": crop.copy(),
            "roi": roi,
            "thumbnail": self.image_to_data_url(crop, size=96),
        }
        self.adding_capture = False
        self.center_hover_roi = None
        self.grid_message = "Скрин узла готов к сохранению"
        self.redraw_overlay()
        self.push_state()

    def save_pending_reference_capture(self, label: str) -> None:
        template = self.current_template()
        if not template:
            raise ValueError("Шаблон не выбран")
        if not self.pending_reference_capture:
            raise ValueError("Нет скрина узла для сохранения")
        label = label.strip() or "template"
        crop = self.pending_reference_capture["image"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        image_path = self.search_template_repo.image_dir / f"{timestamp}.png"
        ok = cv2.imwrite(str(image_path), crop)
        if not ok:
            raise RuntimeError("Не удалось сохранить PNG")
        self.matcher.ensure_template_variant_files(image_path)
        item = {
            "id": image_path.stem,
            "label": label,
            "image_path": str(image_path),
            "image_width": int(crop.shape[1]),
            "image_height": int(crop.shape[0]),
            "match_size": max(32, int(min(crop.shape[:2]))),
            "capture_roi_size": float(self.template.roi_size),
            "crop_ratio": float(NORMALIZATION_CROP_RATIO),
        }
        SearchTemplateRepository.enrich_item_metadata_from_png(item)
        template.setdefault("items", []).append(item)
        self.save_search_data()
        self.pending_reference_capture = None
        self.adding_capture = False
        self.center_hover_roi = None
        self.grid_visible = False
        self.grid_message = "Сетка показана" if self.grid_visible else "Сетка сохранена"
        self.hide_overlay_if_unused()
        self.redraw_overlay()
        self.status_message = f"Добавлен скрин: {label}"
        self.add_log(f"Reference captured: {label}")

    def capture_reference(self, label: str) -> None:
        template = self.current_template()
        if not template:
            raise ValueError("Шаблон не выбран")
        label = label.strip() or "template"
        overlay_was_needed = self.grid_visible or self.adding_capture or self.center_setup_active
        self.overlay.withdraw()
        self.root.update_idletasks()
        image, _ = self.capture_service.capture_primary_monitor()
        if overlay_was_needed:
            self.overlay.deiconify()
        x = int(round(self.ui_state["capture_x"]))
        y = int(round(self.ui_state["capture_y"]))
        w = int(round(self.ui_state["capture_w"]))
        h = int(round(self.ui_state["capture_h"]))
        crop = image[y : y + h, x : x + w]
        if crop.size == 0:
            raise ValueError("Пустая область скрина")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        image_path = self.search_template_repo.image_dir / f"{timestamp}.png"
        ok = cv2.imwrite(str(image_path), crop)
        if not ok:
            raise RuntimeError("Не удалось сохранить PNG")
        self.matcher.ensure_template_variant_files(image_path)
        item = {
            "id": image_path.stem,
            "label": label,
            "image_path": str(image_path),
            "image_width": int(crop.shape[1]),
            "image_height": int(crop.shape[0]),
            "match_size": max(32, int(min(crop.shape[:2]))),
            "capture_roi_size": float(self.template.roi_size),
            "crop_ratio": float(NORMALIZATION_CROP_RATIO),
        }
        SearchTemplateRepository.enrich_item_metadata_from_png(item)
        template.setdefault("items", []).append(item)
        self.save_search_data()
        self.status_message = f"Добавлен скрин: {label}"
        self.add_log(f"Reference captured: {label}")

    def delete_item_file_if_unreferenced(self, item: dict) -> None:
        image_path = item.get("image_path")
        if not image_path or self.image_path_is_referenced(image_path):
            return
        try:
            Path(image_path).unlink(missing_ok=True)
        except OSError:
            logger.exception("Unable to delete unreferenced image: %s", image_path)

    def image_path_is_referenced(self, image_path: str) -> bool:
        target = str(Path(image_path))
        for item in self.iter_search_items():
            if str(Path(item.get("image_path", ""))) == target:
                return True
        return False

    def toggle_grid(self) -> None:
        self.center_setup_active = False
        self.center_hover_roi = None
        if self.center_machine.state != CENTER_CONFIRMED:
            self.grid_visible = False
            self.grid_message = "Сначала подтвердите центр Bloodweb"
            self.hide_overlay_if_unused()
            self.redraw_overlay()
            self.push_state()
            return
        self.grid_visible = not self.grid_visible
        self.grid_message = "Сетка показана" if self.grid_visible else "Сетка сохранена"
        self.show_overlay_if_needed() if self.grid_visible else self.hide_overlay_if_unused()
        self.redraw_overlay()
        self.add_log("Grid shown" if self.grid_visible else "Grid hidden")

    def show_overlay_if_needed(self) -> None:
        if self.grid_visible or self.adding_capture or self.center_setup_active:
            self.overlay.deiconify()
            self.overlay.lift()
            self.overlay.attributes("-topmost", True)

    def hide_overlay_if_unused(self) -> None:
        if not self.grid_visible and not self.adding_capture and not self.center_setup_active:
            self.overlay.withdraw()

    def set_capture_size_from_grid(self) -> None:
        size = max(16.0, float(self.template.roi_size) * CAPTURE_BOX_ROI_RATIO)
        self.ui_state["capture_w"] = size
        self.ui_state["capture_h"] = size

    def redraw_overlay(self) -> None:
        self.canvas.delete("all")
        if self.center_setup_active:
            self.draw_center_marker()
            return
        if self.grid_visible:
            self.draw_grid()

    def draw_grid(self) -> None:
        for ring, spec in RING_SPECS.items():
            radius = getattr(self.template, f"ring{ring}_radius")
            color = {1: "#57d37b", 2: "#4aa3ff", 3: "#bf7dff"}[ring]
            self.canvas.create_oval(
                self.template.center_x - radius,
                self.template.center_y - radius,
                self.template.center_x + radius,
                self.template.center_y + radius,
                outline=color,
                width=1,
            )
            for index in range(spec["count"]):
                x, y = self.node_position(ring, index)
                half = self.template.roi_size / 2.0
                highlighted = self.center_hover_roi is not None and self.center_hover_roi.ring == ring and self.center_hover_roi.index == index
                if self.adding_capture:
                    self.canvas.create_rectangle(
                        x - half,
                        y - half,
                        x + half,
                        y + half,
                        fill="#202421",
                        outline="#ffcc33" if highlighted else color,
                        stipple="gray12",
                        width=3 if highlighted else 2,
                    )
                    if highlighted:
                        self.canvas.create_rectangle(
                            x - half,
                            y - half,
                            x + half,
                            y + half,
                            fill="#ffcc33",
                            outline="#ffcc33",
                            stipple="gray50",
                            width=2,
                        )
                else:
                    self.canvas.create_rectangle(
                        x - half,
                        y - half,
                        x + half,
                        y + half,
                        outline="#ffcc33" if highlighted else color,
                        width=4 if highlighted else 2,
                    )
        if not self.center_anchor_has_fixed_point():
            x = self.template.center_x
            y = self.template.center_y
            self.canvas.create_line(x - 18, y, x + 18, y, fill="#ffffff", width=2)
            self.canvas.create_line(x, y - 18, x, y + 18, fill="#ffffff", width=2)
        if not self.adding_capture:
            self.draw_grid_resize_handles()
            self.draw_grid_reset_control()

    def center_anchor_has_fixed_point(self) -> bool:
        return bool(
            self.center_anchor
            and self.center_anchor.center_x is not None
            and self.center_anchor.center_y is not None
        )

    def can_capture_center_with_overlay_visible(self) -> bool:
        if not self.center_anchor_has_fixed_point() or self.center_setup_active:
            return False
        anchor_size = 0.0
        if self.center_anchor and self.center_anchor.roi_size:
            anchor_size = float(max(self.center_anchor.roi_size))
        center_half = max(anchor_size, float(self.template.roi_size)) / 2.0
        return center_half + 8.0 < float(self.template.ring1_radius)

    def draw_center_setup_hint(self) -> None:
        self.canvas.create_text(
            self.template.center_x,
            max(24, self.template.center_y - self.template.ring3_radius - 30),
            text="Выберите узел центра Bloodweb",
            fill="#ffcc33",
            font=("Segoe UI", 13, "bold"),
        )

    def draw_center_marker(self) -> None:
        x = float(self.center_marker_x)
        y = float(self.center_marker_y)
        radius = max(20.0, float(self.template.roi_size) / 2.0)
        button_w = 94.0
        button_h = 26.0
        button_gap = 8.0
        button_y1 = y + radius + 12.0
        button_y2 = button_y1 + button_h

        self.canvas.create_oval(
            x - radius,
            y - radius,
            x + radius,
            y + radius,
            outline="#ffcc33",
            width=3,
        )
        self.canvas.create_oval(x + radius - 6, y - 6, x + radius + 6, y + 6, fill="#ffffff", outline="#111111", width=1)
        hex_radius = radius * 0.9
        hex_points: list[float] = []
        for index in range(6):
            angle = math.radians(-90.0 + index * 60.0)
            hex_points.extend((x + math.cos(angle) * hex_radius, y + math.sin(angle) * hex_radius))
        self.canvas.create_polygon(*hex_points, outline="#eef0ec", fill="", width=2)
        self.canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="#ffcc33", outline="#111111", width=1)
        self.canvas.create_line(x - 22, y, x - 8, y, fill="#ffcc33", width=2)
        self.canvas.create_line(x + 8, y, x + 22, y, fill="#ffcc33", width=2)
        self.canvas.create_line(x, y - 22, x, y - 8, fill="#ffcc33", width=2)
        self.canvas.create_line(x, y + 8, x, y + 22, fill="#ffcc33", width=2)

        total_w = button_w * 3.0 + button_gap * 2.0
        start_x = x - total_w / 2.0
        confirm = (start_x, button_y1, start_x + button_w, button_y2)
        reset = (start_x + button_w + button_gap, button_y1, start_x + button_w * 2.0 + button_gap, button_y2)
        cancel = (start_x + button_w * 2.0 + button_gap * 2.0, button_y1, start_x + total_w, button_y2)
        self.center_confirm_rect = confirm
        self.center_reset_rect = reset
        self.center_cancel_rect = cancel
        self.canvas.create_rectangle(*confirm, fill="#385437", outline="#87b66e", width=1)
        self.canvas.create_text((confirm[0] + confirm[2]) / 2, (confirm[1] + confirm[3]) / 2, text="Подтвердить", fill="#eef0ec", font=("Segoe UI", 9, "bold"))
        self.canvas.create_rectangle(*reset, fill="#2d332f", outline="#6f9166", width=1)
        self.canvas.create_text((reset[0] + reset[2]) / 2, (reset[1] + reset[3]) / 2, text="Сброс", fill="#d7ecd0", font=("Segoe UI", 9, "bold"))
        self.canvas.create_rectangle(*cancel, fill="#252a27", outline="#3a3f3d", width=1)
        self.canvas.create_text((cancel[0] + cancel[2]) / 2, (cancel[1] + cancel[3]) / 2, text="Отмена", fill="#a6aca5", font=("Segoe UI", 9))

    @staticmethod
    def point_in_rect(x: float, y: float, rect: tuple[float, float, float, float] | None) -> bool:
        if rect is None:
            return False
        return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]

    def hit_center_marker_panel(self, x: float, y: float) -> bool:
        radius = max(20.0, float(self.template.roi_size) / 2.0)
        left = self.center_marker_x - radius
        right = self.center_marker_x + radius
        bottom = self.center_cancel_rect[3] if self.center_cancel_rect else self.center_marker_y + radius
        if self.center_confirm_rect and self.center_cancel_rect:
            left = min(left, self.center_confirm_rect[0])
            right = max(right, self.center_cancel_rect[2])
        return (
            left <= x <= right
            and self.center_marker_y - radius <= y <= bottom
        )

    def hit_center_resize_edge(self, x: float, y: float) -> bool:
        radius = max(20.0, float(self.template.roi_size) / 2.0)
        distance = math.hypot(x - self.center_marker_x, y - self.center_marker_y)
        return abs(distance - radius) <= 12.0

    def draw_grid_resize_handles(self) -> None:
        colors = {1: "#57d37b", 2: "#4aa3ff", 3: "#bf7dff"}
        for ring in (1, 2, 3):
            radius = getattr(self.template, f"ring{ring}_radius")
            for x, y in (
                (self.template.center_x + radius, self.template.center_y),
                (self.template.center_x - radius, self.template.center_y),
                (self.template.center_x, self.template.center_y + radius),
                (self.template.center_x, self.template.center_y - radius),
            ):
                self.canvas.create_oval(x - 7, y - 7, x + 7, y + 7, fill=colors[ring], outline="#111111")

    def draw_grid_reset_control(self) -> None:
        x1 = self.template.center_x - 76
        y1 = max(12, self.template.center_y - self.template.ring3_radius - 46)
        x2 = self.template.center_x + 76
        y2 = y1 + 26
        self.grid_reset_rect = (x1, y1, x2, y2)
        self.canvas.create_rectangle(x1, y1, x2, y2, fill="#252a27", outline="#6f9166", width=1)
        self.canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text="Сбросить размер", fill="#d7ecd0", font=("Segoe UI", 9, "bold"))

    def reset_grid_size(self) -> None:
        self.template.ring1_radius = 95.0
        self.template.ring2_radius = 190.0
        self.template.ring3_radius = 285.0
        self.save_grid_template(self.template)
        self.redraw_overlay()
        self.add_log("Grid size reset")
        self.push_state()

    def draw_capture_box(self) -> None:
        x = self.ui_state["capture_x"]
        y = self.ui_state["capture_y"]
        w = self.ui_state["capture_w"]
        h = self.ui_state["capture_h"]
        self.canvas.create_rectangle(x, y, x + w, y + h, outline="#ffcc33", width=3)
        self.canvas.create_text(x + w / 2, y - 14, text="Эталон", fill="#ffcc33", font=("Segoe UI", 12, "bold"))

    def node_position(self, ring: int, index: int) -> tuple[float, float]:
        spec = RING_SPECS[ring]
        radius = getattr(self.template, f"ring{ring}_radius")
        angle_deg = spec["angles_deg"][index] + self.template.rotation_deg
        angle = math.radians(angle_deg)
        return self.template.center_x + math.cos(angle) * radius, self.template.center_y + math.sin(angle) * radius

    def cancel_overlay_mode(self) -> None:
        if self.center_setup_active or self.pending_center_anchor:
            self.cancel_pending_center_anchor()
            self.push_state()
            return
        if self.adding_capture or self.pending_reference_capture:
            self.cancel_reference_capture()
            self.push_state()
            return
        self.close_add_capture()

    def on_overlay_motion(self, event: tk.Event) -> None:
        if self.adding_capture:
            roi = self.roi_at_point(event.x, event.y)
            if (roi.node_id if roi else None) != (self.center_hover_roi.node_id if self.center_hover_roi else None):
                self.center_hover_roi = roi
                self.redraw_overlay()
            self.overlay.config(cursor="hand2" if roi else "")
            return
        if not self.center_setup_active:
            if self.grid_visible:
                self.overlay.config(cursor="sizing" if self.hit_grid_resize_edge(event.x, event.y) else "")
            return
        if self.hit_center_resize_edge(event.x, event.y):
            self.overlay.config(cursor="sizing")
        else:
            self.overlay.config(cursor="fleur" if self.hit_center_marker_panel(event.x, event.y) else "")

    def roi_at_point(self, x: float, y: float) -> NodeROI | None:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        for roi in build_rois(self.template, screen_w, screen_h):
            if roi.x1 <= x <= roi.x2 and roi.y1 <= y <= roi.y2:
                return roi
        return None

    def on_left_press(self, event: tk.Event) -> None:
        if self.center_setup_active:
            if self.point_in_rect(event.x, event.y, self.center_confirm_rect):
                self.save_center_anchor_from_marker()
                return
            if self.point_in_rect(event.x, event.y, self.center_cancel_rect):
                self.cancel_pending_center_anchor()
                self.push_state()
                return
            if self.point_in_rect(event.x, event.y, self.center_reset_rect):
                self.reset_center_setup_scale()
                return
            if self.hit_center_resize_edge(event.x, event.y):
                distance = max(1.0, math.hypot(event.x - self.center_marker_x, event.y - self.center_marker_y))
                self.center_resize_data = (
                    distance,
                    self.template.ring1_radius,
                    self.template.ring2_radius,
                    self.template.ring3_radius,
                    self.template.roi_size,
                )
                return
            if self.hit_center_marker_panel(event.x, event.y):
                self.center_marker_drag_data = (event.x, event.y, self.center_marker_x, self.center_marker_y)
            return
        if self.adding_capture:
            roi = self.roi_at_point(event.x, event.y)
            if roi:
                self.capture_reference_candidate(roi)
            return
        if self.grid_visible and self.point_in_rect(event.x, event.y, self.grid_reset_rect):
            self.reset_grid_size()
            return
        resize_ring = self.hit_grid_resize_edge(event.x, event.y) if self.grid_visible else None
        if resize_ring is not None:
            distance = max(1.0, math.hypot(event.x - self.template.center_x, event.y - self.template.center_y))
            self.grid_resize_data = (resize_ring, distance, getattr(self.template, f"ring{resize_ring}_radius"))
            return

    def on_left_drag(self, event: tk.Event) -> None:
        if self.center_marker_drag_data:
            start_x, start_y, marker_x, marker_y = self.center_marker_drag_data
            self.center_marker_x = max(0.0, marker_x + (event.x - start_x))
            self.center_marker_y = max(0.0, marker_y + (event.y - start_y))
            self.redraw_overlay()
            return
        if self.center_resize_data:
            start_distance, ring1, ring2, ring3, roi_size = self.center_resize_data
            current_distance = max(1.0, math.hypot(event.x - self.center_marker_x, event.y - self.center_marker_y))
            factor = max(0.2, min(5.0, current_distance / start_distance))
            self.template.ring1_radius = max(20.0, ring1 * factor)
            self.template.ring2_radius = max(40.0, ring2 * factor)
            self.template.ring3_radius = max(60.0, ring3 * factor)
            self.template.roi_size = max(16.0, min(220.0, roi_size * factor))
            self.set_capture_size_from_grid()
            self.save_grid_template(self.template)
            self.redraw_overlay()
            return
        if self.capture_drag_data:
            start_x, start_y, box_x, box_y = self.capture_drag_data
            self.ui_state["capture_x"] = max(0.0, box_x + (event.x - start_x))
            self.ui_state["capture_y"] = max(0.0, box_y + (event.y - start_y))
            self.save_ui_state()
            self.redraw_overlay()
            return
        if self.grid_resize_data:
            ring, start_distance, start_radius = self.grid_resize_data
            current_distance = max(1.0, math.hypot(event.x - self.template.center_x, event.y - self.template.center_y))
            radius = self.clamp_ring_radius(ring, start_radius * current_distance / start_distance)
            setattr(self.template, f"ring{ring}_radius", radius)
            self.save_grid_template(self.template)
            self.redraw_overlay()
            return
        if self.grid_drag_data:
            start_x, start_y, center_x, center_y = self.grid_drag_data
            self.template.center_x = center_x + (event.x - start_x)
            self.template.center_y = center_y + (event.y - start_y)
            self.save_grid_template(self.template)
            self.redraw_overlay()

    def on_left_release(self, _event: tk.Event) -> None:
        self.grid_drag_data = None
        self.grid_resize_data = None
        self.capture_drag_data = None
        self.center_marker_drag_data = None
        self.center_resize_data = None

    def on_mouse_wheel(self, event: tk.Event) -> None:
        if self.center_setup_active:
            factor = 1.06 if event.delta > 0 else 0.94
            self.scale_grid_from_node_size(factor)
            return
        if not self.grid_visible:
            return
        factor = 1.04 if event.delta > 0 else 0.96
        self.scale_grid_from_node_size(factor)

    def scale_grid_from_node_size(self, factor: float) -> None:
        self.template.ring1_radius = max(20.0, self.template.ring1_radius * factor)
        self.template.ring2_radius = max(40.0, self.template.ring2_radius * factor)
        self.template.ring3_radius = max(60.0, self.template.ring3_radius * factor)
        self.template.roi_size = max(16.0, min(220.0, self.template.roi_size * factor))
        self.set_capture_size_from_grid()
        self.save_grid_template(self.template)
        self.redraw_overlay()

    def reset_center_setup_scale(self) -> None:
        self.template.ring1_radius = 95.0
        self.template.ring2_radius = 190.0
        self.template.ring3_radius = 285.0
        self.template.roi_size = 70.0
        self.set_capture_size_from_grid()
        self.save_grid_template(self.template)
        self.redraw_overlay()

    def hit_capture_box(self, x: float, y: float) -> bool:
        padding = 24.0
        return (
            self.ui_state["capture_x"] - padding <= x <= self.ui_state["capture_x"] + self.ui_state["capture_w"] + padding
            and self.ui_state["capture_y"] - padding <= y <= self.ui_state["capture_y"] + self.ui_state["capture_h"] + padding
        )

    def hit_grid_resize_edge(self, x: float, y: float) -> int | None:
        distance = math.hypot(x - self.template.center_x, y - self.template.center_y)
        matches = []
        for ring in (1, 2, 3):
            radius = getattr(self.template, f"ring{ring}_radius")
            delta = abs(distance - radius)
            if delta <= 18.0:
                matches.append((delta, ring))
        if not matches:
            return None
        return min(matches)[1]

    def clamp_ring_radius(self, ring: int, value: float) -> float:
        value = max(20.0, float(value))
        if ring == 1:
            return min(value, self.template.ring2_radius)
        if ring == 2:
            return max(self.template.ring1_radius, min(value, self.template.ring3_radius))
        return max(value, self.template.ring2_radius)

    def save_grid_template(self, template: GridTemplate) -> None:
        payload = {"schema_version": 2, "description": "Manual Bloodweb grid calibration templates.", "templates": [asdict(template)]}
        (ROOT / "db" / "grid_templates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_click_queue(self) -> None:
        self.status = "Тест"
        self.status_message = "Тест: построение очереди"
        self.add_log("Test queue requested")
        detections = self.build_click_queue_from_screenshot()
        self.set_queue_from_detections(detections)
        if not self.build_search_items():
            self.status = "Пауза"
            self.status_message = "Нет элементов для поиска"
            return
        self.status = "Готов"
        self.status_message = "Очередь построена"
        self.push_state()

    def build_click_queue_from_screenshot(self) -> list[dict]:
        items = self.build_search_items()
        if not items:
            self.next_click = None
            return []
        image, _ = self.capture_clean_screen()
        rois = build_rois(self.template, image.shape[1], image.shape[0])
        return self.detect_in_rois(image, rois, items)

    def capture_clean_screen(self):
        self.root.update_idletasks()
        self.capture_exclusion_rect = self.electron_window_rect
        overlay_was_needed = self.grid_visible or self.adding_capture
        self.overlay.withdraw()
        self.root.update_idletasks()
        self.park_mouse_for_screenshot()
        image, meta = self.capture_service.capture_primary_monitor()
        if overlay_was_needed:
            self.overlay.deiconify()
            self.overlay.lift()
            self.overlay.attributes("-topmost", True)
        return image, meta

    def park_mouse_for_screenshot(self) -> None:
        if self.stop_requested and self.emergency_stop_reason in {"manual_mouse_move", "hotkey_f8", "stop_button"}:
            return
        self.run_programmatic_mouse_action(SCREENSHOT_MOUSE_PARKING_POSITION, lambda: self.mouse_controller.move_to(*SCREENSHOT_MOUSE_PARKING_POSITION))
        self.root.update_idletasks()
        time.sleep(_safe_float(self.ui_state.get("screenshot_settle_seconds"), SCREENSHOT_AFTER_MOUSE_MOVE_DELAY_SECONDS, 0.0, 2.0))

    def capture_clean_screen_threadsafe(self):
        self.screenshot_result = None
        self.screenshot_request_lock.clear()
        self.root.after(0, self.capture_clean_screen_for_worker)
        self.screenshot_request_lock.wait()
        if self.screenshot_result is None:
            raise RuntimeError("Не удалось сделать чистый скриншот")
        return self.screenshot_result

    def capture_clean_screen_for_worker(self) -> None:
        try:
            self.screenshot_result = self.capture_clean_screen()
        finally:
            self.screenshot_request_lock.set()

    def capture_screen_without_mouse_move(self, hide_overlay: bool = True):
        self.root.update_idletasks()
        self.capture_exclusion_rect = self.electron_window_rect
        overlay_was_needed = self.grid_visible or self.adding_capture or self.center_setup_active
        should_hide_overlay = hide_overlay and overlay_was_needed
        if should_hide_overlay:
            self.overlay.withdraw()
            self.root.update_idletasks()
        image, meta = self.capture_service.capture_primary_monitor()
        if should_hide_overlay:
            self.overlay.deiconify()
            self.overlay.lift()
            self.overlay.attributes("-topmost", True)
        return image, meta

    def capture_screen_without_mouse_move_threadsafe(self, hide_overlay: bool = True):
        self.screenshot_result = None
        self.screenshot_request_lock.clear()
        self.root.after(0, lambda: self.capture_screen_without_mouse_move_for_worker(hide_overlay))
        self.screenshot_request_lock.wait()
        if self.screenshot_result is None:
            raise RuntimeError("Не удалось сделать скриншот для проверки центра")
        return self.screenshot_result

    def capture_screen_without_mouse_move_for_worker(self, hide_overlay: bool = True) -> None:
        try:
            self.screenshot_result = self.capture_screen_without_mouse_move(hide_overlay=hide_overlay)
        finally:
            self.screenshot_request_lock.set()

    def detect_in_rois(self, image, rois, items: list[dict]) -> list[dict]:
        ranked = {item["id"]: index for index, item in enumerate(items)}
        best_by_item: dict[str, dict] = {}
        prepared_items = self.matcher.prepare_items(items)
        threshold = float(self.ui_state.get("threshold", 0.80))
        detail_min = float(self.ui_state.get("detailed_match_min_score", DETAILED_MATCH_MIN_SCORE))
        detail_max = float(self.ui_state.get("detailed_match_max_score", DETAILED_MATCH_MAX_SCORE))
        for roi in rois:
            if self.roi_intersects_exclusion(roi):
                continue
            crop = image[roi.y1 : roi.y2, roi.x1 : roi.x2]
            if crop.size == 0 or not self.matcher.roi_has_node_like_content(crop):
                continue
            crop = self.center_crop(crop, CAPTURE_BOX_ROI_RATIO)
            candidates = self.matcher.match_roi_prepared(crop, prepared_items, top_n=max(2, len(prepared_items)), roi_id=roi.node_id)
            if not candidates:
                continue
            best = candidates[0]
            second = candidates[1]["score"] if len(candidates) > 1 else -1.0
            if best["score"] < threshold:
                continue
            if self.matcher.should_run_detail_verification(best["score"], detail_min, detail_max):
                detail = self.matcher.verify_candidate_detail(best, roi_id=roi.node_id)
                self.add_log(f"detail_verify {best['label']} {roi.node_id}: {detail}")
                if not detail["detail_passed"]:
                    self.add_log(f"REJECT detail {best['label']} {roi.node_id}")
                    continue
            if len(candidates) > 1 and best["score"] - second < MATCH_MARGIN_THRESHOLD:
                self.add_log(f"REJECT margin {best['label']} {roi.node_id}")
                continue
            match = {
                "id": best["id"],
                "label": best["label"],
                "image_path": best["image_path"],
                "thumbnail": self.thumbnail_data_url(best["image_path"]),
                "score": best["score"],
                "margin": best["score"] - second,
                "node_id": roi.node_id,
                "x": roi.center_x,
                "y": roi.center_y,
                "distance": roi.distance_from_center,
                "rank": ranked.get(best["id"], 10_000),
                "action": "item",
            }
            previous = best_by_item.get(best["id"])
            if previous is None or (match["distance"], match["score"]) > (previous["distance"], previous["score"]):
                best_by_item[best["id"]] = match
        matches = list(best_by_item.values())
        matches.sort(key=lambda item: (item["rank"], -item["distance"], -item["score"]))
        self.add_log(f"Queue matches: {len(matches)}")
        return matches

    def roi_intersects_exclusion(self, roi) -> bool:
        rect = self.capture_exclusion_rect
        if rect is None:
            return False
        x1, y1, x2, y2 = rect
        return roi.x1 < x2 and roi.x2 > x1 and roi.y1 < y2 and roi.y2 > y1

    @staticmethod
    def center_crop(image, ratio: float):
        if ratio >= 1.0:
            return image
        height, width = image.shape[:2]
        crop_w = max(1, int(round(width * ratio)))
        crop_h = max(1, int(round(height * ratio)))
        x1 = max(0, (width - crop_w) // 2)
        y1 = max(0, (height - crop_h) // 2)
        return image[y1 : y1 + crop_h, x1 : x1 + crop_w]

    def set_queue_from_detections(self, detections: list[dict]) -> None:
        queue_items = []
        for index, detection in enumerate(detections, start=1):
            item = dict(detection)
            item["position"] = index
            queue_items.append(item)
        center = {
            "id": "center",
            "label": "Центр",
            "position": len(queue_items) + 1,
            "action": "center",
            "x": int(round(self.template.center_x)),
            "y": int(round(self.template.center_y)),
        }
        queue_items.append(center)
        self.queue_items = queue_items
        self.next_click = queue_items[0] if queue_items else None

    def start_center_monitor(self) -> None:
        if self.center_check_thread and self.center_check_thread.is_alive():
            return
        self.center_check_thread = threading.Thread(target=self.center_monitor_loop, daemon=True)
        self.center_check_thread.start()

    def center_monitor_loop(self) -> None:
        time.sleep(0.5)
        while not self.center_check_stop.is_set():
            try:
                self.run_center_check_cycle()
            except Exception as exc:
                logger.exception("center_check failed")
                self.center_last_message = f"Ошибка проверки центра: {exc}"
                self.clicks_allowed_event.clear()
                if self.is_auto_running():
                    self.emergency_stop("screenshot_error")
            self.center_check_stop.wait(CENTER_CHECK_INTERVAL_SECONDS)

    def run_center_check_cycle(self) -> None:
        if not self.center_anchor:
            self.center_anchor = self.center_anchor_repo.load()
            if not self.center_anchor:
                with self.safety_lock:
                    self.center_machine.set_configured(False)
                    self.clicks_allowed_event.clear()
                    self.center_last_score = None
                    self.center_last_message = "Центр Bloodweb не настроен"
                self.push_state()
                return
            with self.safety_lock:
                self.center_machine.set_configured(True)

        success, score = self.check_center_once()
        with self.safety_lock:
            previous_state = self.center_machine.state
            event = self.center_machine.regular_result(success)
            self.sync_click_event()
            self.center_last_score = score
            self.center_last_message = self.message_for_center_state()
        log_line = (
            f"center_check: score={score:.4f} threshold={self.center_threshold():.4f} "
            f"result={'CONFIRMED' if success else 'MISS'} state={self.center_machine.state}"
        )
        if not success or previous_state != self.center_machine.state or event != "none":
            self.add_log(log_line)
        else:
            logger.debug(log_line)
        if previous_state != self.center_machine.state or event != "none":
            self.push_state()
        if event == "recheck":
            self.status_message = "Перепроверка центра"
            self.push_state()
            self.run_center_rechecks()

    def run_center_rechecks(self) -> None:
        results = []
        for attempt in (1, 2):
            if self.center_check_stop.wait(CENTER_RECHECK_DELAY_SECONDS):
                return
            try:
                success, score = self.check_center_once()
            except Exception:
                logger.exception("center_recheck failed")
                success, score = False, 0.0
            results.append(success)
            self.center_last_score = score
            self.add_log(
                f"center_recheck: attempt={attempt} score={score:.4f} "
                f"result={'CONFIRMED' if success else 'MISS'}"
            )
            if success:
                break
        with self.safety_lock:
            event = self.center_machine.recheck_results(results)
            self.sync_click_event()
            self.center_last_message = self.message_for_center_state()
        self.push_state()
        if event == "lost":
            if self.is_auto_running():
                self.status = "Пауза"
                self.status_message = "Ждём появления центра Bloodweb"
                self.add_log("Center lost during Start: waiting for confirmation")
                self.push_state()

    def check_center_once(self) -> tuple[bool, float]:
        anchor = self.center_anchor_repo.load()
        if not anchor:
            self.center_anchor = None
            self.center_machine.set_configured(False)
            self.clicks_allowed_event.clear()
            return False, 0.0
        self.center_anchor = anchor
        anchor_image = imread_unicode(anchor.image_path, cv2.IMREAD_UNCHANGED)
        if anchor_image is None or anchor_image.size == 0:
            self.center_anchor = None
            self.center_machine.set_configured(False)
            self.clicks_allowed_event.clear()
            return False, 0.0
        image, _ = self.capture_screen_without_mouse_move_threadsafe(
            hide_overlay=not self.can_capture_center_with_overlay_visible()
        )
        roi = self.center_roi_for_image(anchor.node_id, image.shape[1], image.shape[0])
        if roi is None:
            return False, 0.0
        crop = image[roi.y1 : roi.y2, roi.x1 : roi.x2]
        if crop.size == 0:
            return False, 0.0
        match_size = max(32, int(min(anchor.roi_size)))
        score = self.center_anchor_matcher.score(anchor_image, crop, match_size, anchor.crop_ratio)
        return score >= self.center_threshold(), score

    def center_roi_for_image(self, node_id: str, image_width: int, image_height: int) -> NodeROI | None:
        anchor = self.center_anchor
        if anchor and anchor.center_x is not None and anchor.center_y is not None:
            size = max(20, int(round(max(anchor.roi_size or [0]))))
            half = size / 2.0
            x = float(anchor.center_x)
            y = float(anchor.center_y)
            x1 = max(0, int(round(x - half)))
            y1 = max(0, int(round(y - half)))
            x2 = min(image_width, int(round(x + half)))
            y2 = min(image_height, int(round(y + half)))
            if x2 - x1 < 10 or y2 - y1 < 10:
                return None
            return NodeROI(
                node_id="center_point",
                ring=0,
                index=0,
                angle_deg=0.0,
                center_x=x,
                center_y=y,
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                distance_from_center=0.0,
            )
        for roi in build_rois(self.template, image_width, image_height):
            if roi.node_id == node_id:
                return roi
        return None

    def center_threshold(self) -> float:
        return _safe_float(
            self.ui_state.get("center_anchor_confidence_threshold"),
            CENTER_ANCHOR_DEFAULT_THRESHOLD,
            0.0,
            1.0,
        )

    def sync_click_event(self) -> None:
        if self.center_machine.clicks_allowed:
            self.clicks_allowed_event.set()
        else:
            self.clicks_allowed_event.clear()

    def message_for_center_state(self) -> str:
        state = self.center_machine.state
        if state == CENTER_CONFIRMED:
            return "Центр Bloodweb подтверждён. Автоклик разрешён."
        if state == CENTER_RECHECKING:
            return "Клики временно заблокированы: идёт перепроверка центра."
        if state == CENTER_NOT_CONFIRMED:
            return "Центр Bloodweb не подтверждён. Автоклик заблокирован."
        return "Центр Bloodweb не настроен. Нажмите, чтобы настроить центр."

    def is_auto_running(self) -> bool:
        return bool(self.auto_thread and self.auto_thread.is_alive() and not self.stop_requested)

    def start_auto(self) -> None:
        if self.auto_thread and self.auto_thread.is_alive():
            return
        if not self.safety_consent_accepted():
            self.status = "Пауза"
            self.status_message = "Start заблокирован: требуется согласие"
            self.push_state()
            return
        if self.center_machine.state != CENTER_CONFIRMED or not self.clicks_allowed_event.is_set():
            self.status = "Пауза"
            self.status_message = "Start заблокирован: центр Bloodweb не подтверждён"
            self.push_state()
            return
        items = self.build_search_items()
        if not items:
            self.status = "Пауза"
            self.status_message = "Нет элементов для поиска"
            return
        self.stop_requested = False
        self.restart_auto_cycle_requested = False
        self.mouse_stop_notified = False
        self.set_expected_mouse_position(self.mouse_controller.mouse.position)
        self.status = "Работа"
        self.status_message = "Работает"
        self.overlay.withdraw()
        self.start_mouse_monitor()
        self.auto_thread = threading.Thread(target=self.auto_loop, daemon=True)
        self.auto_thread.start()
        self.add_log("Start")
        self.push_state()

    def stop_auto(self) -> None:
        return self.emergency_stop("stop_button")
        self.stop_requested = True
        self.mouse_stop_notified = True
        self.status = "Готов"
        self.status_message = "Остановлено"
        if self.grid_visible or self.adding_capture:
            self.overlay.deiconify()
            self.overlay.lift()
        self.add_log("Stop")
        self.push_state()

    def start_hotkey_listener(self) -> None:
        if self.keyboard_listener is not None:
            return

        def on_press(key) -> None:
            if key == keyboard.Key.f8:
                self.emergency_stop("hotkey_f8")

        try:
            self.keyboard_listener = keyboard.Listener(on_press=on_press)
            self.keyboard_listener.daemon = True
            self.keyboard_listener.start()
            self.add_log("F8 emergency hotkey ready")
        except Exception:
            logger.exception("Unable to start F8 listener")

    def emergency_stop(self, reason: str) -> None:
        with self.stop_lock:
            self.stop_requested = True
            self.mouse_stop_notified = True
            self.emergency_stop_reason = reason
            self.clicks_allowed_event.clear()
            self.queue_items = []
            self.next_click = None
            try:
                self.mouse_controller.release_left()
            except Exception:
                logger.exception("Unable to release mouse button during emergency stop")
            self.add_log(f"Emergency stop: {reason}")

        def callback() -> None:
            if self.grid_visible or self.adding_capture or self.center_setup_active:
                self.overlay.deiconify()
                self.overlay.lift()
            self.status = self.emergency_status(reason)
            self.status_message = self.emergency_message(reason)
            self.push_state()

        try:
            self.root.after(0, callback)
        except RuntimeError:
            callback()

    @staticmethod
    def emergency_status(reason: str) -> str:
        if reason == "manual_mouse_move":
            return "Пауза"
        if reason in {"screenshot_error", "matcher_error", "unexpected_error"}:
            return "Ошибка"
        return "Стоп"

    @staticmethod
    def emergency_message(reason: str) -> str:
        labels = {
            "manual_mouse_move": "Аварийная остановка: мышь сдвинули",
            "hotkey_f8": "Аварийная остановка сработала: F8",
            "stop_button": "Аварийная остановка сработала: Stop",
            "center_not_confirmed": "Аварийная остановка: центр Bloodweb не распознан",
            "center_lost_timeout": "Аварийная остановка: центр Bloodweb не появился за отведённое время",
            "screenshot_error": "Аварийная остановка: ошибка скриншота",
            "matcher_error": "Аварийная остановка: ошибка распознавания",
            "unexpected_error": "Аварийная остановка: неожиданная ошибка",
        }
        return labels.get(reason, f"Аварийная остановка: {reason}")

    def auto_loop(self) -> None:
        expected_position = self.mouse_controller.mouse.position
        while not self.stop_requested:
            current_expected = self.expected_mouse_position or expected_position
            if self.mouse_moved_by_user(current_expected):
                self.stop_after_mouse_move()
                return
            items = self.build_search_items()
            if not items:
                self.after_stop("Ошибка: список пуст")
                return
            try:
                image, _ = self.capture_clean_screen_threadsafe()
            except Exception:
                logger.exception("screenshot_error")
                self.emergency_stop("screenshot_error")
                return
            rois = build_rois(self.template, image.shape[1], image.shape[0])
            try:
                detections = self.detect_in_rois(image, rois, items)
            except Exception:
                logger.exception("matcher_error")
                self.emergency_stop("matcher_error")
                return
            if self.stop_requested:
                return
            self.root.after(0, lambda current=detections: self.set_queue_from_detections(current))
            self.root.after(0, self.push_state)
            if not detections:
                center = (int(round(self.template.center_x)), int(round(self.template.center_y)))
                self.after_next({"id": "center", "label": "Центр", "action": "center", "x": center[0], "y": center[1]})
                if not self.click_center_and_wait(center, self.expected_mouse_position or expected_position):
                    if self.consume_restart_auto_cycle_request():
                        expected_position = SCREENSHOT_MOUSE_PARKING_POSITION
                        continue
                    return
                expected_position = SCREENSHOT_MOUSE_PARKING_POSITION
                continue
            restart_current_cycle = False
            for detection in detections:
                if self.stop_requested:
                    self.after_stop("Готово")
                    return
                target = (int(round(detection["x"])), int(round(detection["y"])))
                self.after_next(detection)
                expected_position = self.execute_safe_click(
                    target,
                    _safe_float(self.ui_state.get("click_hold_seconds"), 0.05, 0.01, 2.0),
                    self.expected_mouse_position or expected_position,
                )
                if expected_position is None:
                    if self.consume_restart_auto_cycle_request():
                        expected_position = SCREENSHOT_MOUSE_PARKING_POSITION
                        restart_current_cycle = True
                        break
                    return
                if not self.sleep_with_mouse_check(
                    _safe_float(self.ui_state.get("delay_between_clicks_seconds"), 3.0, 0.1, 30.0),
                    expected_position,
                    require_clicks=True,
                ):
                    if self.consume_restart_auto_cycle_request():
                        expected_position = SCREENSHOT_MOUSE_PARKING_POSITION
                        restart_current_cycle = True
                        break
                    return
            if restart_current_cycle:
                continue
            center = (int(round(self.template.center_x)), int(round(self.template.center_y)))
            self.after_next({"id": "center", "label": "Центр", "action": "center", "x": center[0], "y": center[1]})
            if not self.click_center_and_wait(center, self.expected_mouse_position or expected_position):
                if self.consume_restart_auto_cycle_request():
                    expected_position = SCREENSHOT_MOUSE_PARKING_POSITION
                    continue
                return
            expected_position = SCREENSHOT_MOUSE_PARKING_POSITION

    def click_center_and_wait(self, center: tuple[int, int], current_position: tuple[int, int]) -> bool:
        expected_position = self.execute_safe_click(
            center,
            _safe_float(self.ui_state.get("center_hold_seconds"), 1.0, 0.1, 10.0),
            current_position,
        )
        if expected_position is None:
            return False
        return self.sleep_with_mouse_check(
            _safe_float(self.ui_state.get("after_center_delay_seconds"), 3.0, 0.1, 30.0),
            expected_position,
            require_clicks=True,
        )

    def consume_restart_auto_cycle_request(self) -> bool:
        if not self.restart_auto_cycle_requested or self.stop_requested:
            return False
        self.restart_auto_cycle_requested = False
        self.queue_items = []
        self.next_click = None
        self.status = "Работа"
        self.status_message = "Центр подтверждён, делаем новый скрин"
        self.root.after(0, self.push_state)
        return True

    def execute_safe_click(self, target: tuple[int, int], hold_seconds: float, current_position: tuple[int, int]) -> tuple[int, int] | None:
        if not self.wait_for_click_permission(current_position):
            return None
        if not self.sleep_with_mouse_check(
            _safe_float(self.ui_state.get("pre_click_delay_seconds"), 0.35, 0.0, 5.0),
            current_position,
            require_clicks=True,
        ):
            self.park_mouse_after_completed_action()
            return None
        if not self.wait_for_click_permission(current_position):
            self.park_mouse_after_completed_action()
            return None
        try:
            self.run_programmatic_mouse_action(
                target,
                lambda: self.mouse_controller.click(target[0], target[1], hold_seconds, before_press=self.assert_clicks_allowed),
            )
        except RuntimeError:
            self.park_mouse_after_completed_action()
            return None
        return self.park_mouse_after_completed_action()

    def assert_clicks_allowed(self) -> None:
        if self.stop_requested or not self.clicks_allowed_event.is_set() or self.center_machine.state != CENTER_CONFIRMED:
            raise RuntimeError("clicks are blocked by center guard")

    def wait_for_click_permission(self, expected_position: tuple[int, int]) -> bool:
        notified_waiting_for_center = False
        center_wait_started: float | None = None
        while not self.stop_requested:
            if self.clicks_allowed_event.is_set() and self.center_machine.state == CENTER_CONFIRMED:
                if notified_waiting_for_center:
                    self.status = "Работа"
                    self.status_message = "Центр подтверждён, делаем новый скрин"
                    self.restart_auto_cycle_requested = True
                    self.push_state()
                    return False
                return True
            if self.center_machine.state in {CENTER_RECHECKING, CENTER_NOT_CONFIRMED}:
                if center_wait_started is None:
                    center_wait_started = time.monotonic()
                if self.is_auto_running() and not notified_waiting_for_center:
                    self.status = "Пауза"
                    self.status_message = "Ждём появления центра Bloodweb"
                    self.push_state()
                    notified_waiting_for_center = True
                timeout = _safe_float(self.ui_state.get("center_lost_timeout_seconds"), 30.0, 1.0, 300.0)
                if time.monotonic() - center_wait_started >= timeout:
                    self.emergency_stop("center_lost_timeout")
                    return False
                if not self.sleep_with_mouse_check(
                    _safe_float(self.ui_state.get("mouse_check_interval_seconds"), 0.03, 0.01, 0.50),
                    expected_position,
                    require_clicks=False,
                ):
                    return False
                continue
            return False
        return False

    def park_mouse_after_completed_action(self) -> tuple[int, int]:
        if self.emergency_stop_reason in {"manual_mouse_move", "hotkey_f8", "stop_button"}:
            return self.normalized_mouse_position(self.mouse_controller.mouse.position)
        self.run_programmatic_mouse_action(
            SCREENSHOT_MOUSE_PARKING_POSITION,
            lambda: self.mouse_controller.move_to(*SCREENSHOT_MOUSE_PARKING_POSITION),
        )
        return SCREENSHOT_MOUSE_PARKING_POSITION

    def sleep_with_mouse_check(self, seconds: float, expected_position: tuple[int, int], require_clicks: bool = False) -> bool:
        self.set_expected_mouse_position(expected_position)
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.stop_requested:
                return False
            if require_clicks and not self.wait_for_click_permission(expected_position):
                return False
            if self.mouse_moved_by_user(expected_position):
                self.stop_after_mouse_move()
                return False
            time.sleep(_safe_float(self.ui_state.get("mouse_check_interval_seconds"), 0.03, 0.01, 0.50))
        return True

    def mouse_moved_by_user(self, expected_position: tuple[int, int], tolerance: float | None = None) -> bool:
        if self.programmatic_mouse_action_active:
            return False
        if time.monotonic() < self.mouse_monitor_paused_until:
            return False
        if tolerance is None:
            tolerance = _safe_float(self.ui_state.get("mouse_move_tolerance_pixels"), 45.0, 10.0, 200.0)
        current = self.mouse_controller.mouse.position
        return math.hypot(current[0] - expected_position[0], current[1] - expected_position[1]) > tolerance

    def set_expected_mouse_position(self, position) -> None:
        self.expected_mouse_position = (int(round(position[0])), int(round(position[1])))

    def run_programmatic_mouse_action(self, expected_position: tuple[int, int], action) -> tuple[int, int]:
        self.programmatic_mouse_action_active = True
        final_position = expected_position
        try:
            self.set_expected_mouse_position(expected_position)
            action()
        finally:
            try:
                final_position = self.normalized_mouse_position(self.mouse_controller.mouse.position)
                self.set_expected_mouse_position(final_position)
            except Exception:
                self.set_expected_mouse_position(expected_position)
            self.programmatic_mouse_action_active = False
            self.mouse_monitor_paused_until = time.monotonic() + 0.35
        return final_position

    @staticmethod
    def normalized_mouse_position(position) -> tuple[int, int]:
        return int(round(position[0])), int(round(position[1]))

    def start_mouse_monitor(self) -> None:
        if self.mouse_monitor_thread and self.mouse_monitor_thread.is_alive():
            return
        self.mouse_monitor_thread = threading.Thread(target=self.mouse_monitor_loop, daemon=True)
        self.mouse_monitor_thread.start()

    def mouse_monitor_loop(self) -> None:
        while not self.stop_requested:
            if self.programmatic_mouse_action_active or time.monotonic() < self.mouse_monitor_paused_until:
                time.sleep(_safe_float(self.ui_state.get("mouse_check_interval_seconds"), 0.03, 0.01, 0.50))
                continue
            expected = self.expected_mouse_position
            if expected is not None and self.mouse_moved_by_user(expected):
                self.stop_after_mouse_move()
                return
            time.sleep(_safe_float(self.ui_state.get("mouse_check_interval_seconds"), 0.03, 0.01, 0.50))

    def stop_after_mouse_move(self) -> None:
        return self.emergency_stop("manual_mouse_move")
        if self.mouse_stop_notified:
            return
        self.mouse_stop_notified = True
        self.stop_requested = True
        self.after_stop("Пауза: мышь сдвинули")

    def after_stop(self, text: str) -> None:
        def callback() -> None:
            if self.grid_visible or self.adding_capture:
                self.overlay.deiconify()
                self.overlay.lift()
            self.status = "Пауза" if text.startswith("Пауза") else "Готов"
            self.status_message = text
            self.stop_requested = True
            self.add_log(text)
            self.push_state()

        self.root.after(0, callback)

    def after_next(self, item: dict) -> None:
        def callback() -> None:
            self.next_click = item
            self.status = "Работа"
            self.status_message = "Работает"
            self.push_state()

        self.root.after(0, callback)

    def read_log_lines(self) -> list[str]:
        lines = [line for line in self.log_lines[-80:] if self.is_public_log_line(line)]
        try:
            if LOG_PATH.exists():
                disk_lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-160:]
                lines = [line for line in disk_lines if self.is_public_log_line(line)] + lines
        except OSError:
            pass
        return lines[-180:]

    def add_log(self, text: str) -> None:
        line = f"{datetime.now():%H:%M:%S} {text}"
        if self.is_public_log_line(line):
            self.log_lines.append(line)
        logger.info(text)

    @staticmethod
    def is_public_log_line(line: str) -> bool:
        return not any(marker in line for marker in CENTER_UI_LOG_MARKERS)


def main() -> None:
    ElectronBackend().run()


if __name__ == "__main__":
    main()

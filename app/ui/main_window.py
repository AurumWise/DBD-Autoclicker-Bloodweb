from __future__ import annotations

import json
import math
import threading
import time
import tkinter as tk
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from PIL import Image, ImageTk

from app.automation.mouse_controller import MouseController
from app.capture.screenshot import ScreenshotService
from app.data.search_template_repository import SearchTemplateRepository
from app.grid.geometry import GridTemplateRepository, build_rois
from app.logging_setup import configure_logging
from app.models import GridTemplate
from app.vision.image_io import imread_unicode
from app.vision.snippet_matcher import SnippetMatcher


ROOT = Path(__file__).resolve().parents[2]
UI_STATE_PATH = ROOT / "db" / "ui_state.json"
RING_SPECS = {
    1: {"count": 6, "start_deg": -90.0, "color": "#57d37b"},
    2: {"count": 12, "start_deg": -75.0, "color": "#4aa3ff"},
    3: {"count": 12, "start_deg": -90.0, "color": "#bf7dff"},
}
CAPTURE_BOX_ROI_RATIO = 1.0
MATCH_MARGIN_THRESHOLD = 0.0
SCREENSHOT_MOUSE_PARKING_POSITION = (0, 0)
SCREENSHOT_AFTER_MOUSE_MOVE_DELAY_SECONDS = 0.2
DETAILED_MATCH_MIN_SCORE = 0.75
DETAILED_MATCH_MAX_SCORE = 0.85


class OverlayApp:
    def __init__(self) -> None:
        configure_logging(ROOT)

        self.root = tk.Tk()
        self.root.withdraw()

        self.template_repo = GridTemplateRepository(ROOT)
        self.search_template_repo = SearchTemplateRepository(ROOT)
        self.capture_service = ScreenshotService(ROOT)
        self.mouse_controller = MouseController()
        self.matcher = SnippetMatcher()

        self.template = self.load_or_create_grid_template()
        self.ui_state = self.load_ui_state()
        self.migrate_ui_state()
        self.search_data = self.search_template_repo.load()
        self.enforce_single_owner_items()
        self.enrich_search_item_sizes()

        self.grid_visible = False
        self.adding_capture = False
        self.grid_drag_data: tuple[float, float, float, float] | None = None
        self.grid_resize_data: tuple[float, float, float, float, float] | None = None
        self.capture_drag_data: tuple[float, float, float, float] | None = None
        self.selection_syncing = False
        self.auto_thread: threading.Thread | None = None
        self.mouse_monitor_thread: threading.Thread | None = None
        self.expected_mouse_position: tuple[int, int] | None = None
        self.mouse_monitor_paused_until = 0.0
        self.programmatic_mouse_action_active = False
        self.mouse_stop_notified = False
        self.stop_requested = False
        self.screenshot_request_lock = threading.Event()
        self.screenshot_result = None
        self.capture_exclusion_rect: tuple[int, int, int, int] | None = None

        self.template_refs: list[tuple[str, int]] = []
        self.item_icons: list[ImageTk.PhotoImage] = []
        self.priority_icons: list[ImageTk.PhotoImage] = []
        self.selected_preview_ref: ImageTk.PhotoImage | None = None
        self.next_preview_ref: ImageTk.PhotoImage | None = None

        self.status_var = tk.StringVar(value="Готово")
        self.grid_button_var = tk.StringVar(value="Показать сетку")
        self.template_var = tk.StringVar()
        self.capture_label_var = tk.StringVar()
        self.threshold_var = tk.DoubleVar(value=float(self.ui_state["threshold"]))
        self.threshold_text_var = tk.StringVar(value=f"{float(self.ui_state['threshold']):.2f}")
        self.pre_click_delay_var = tk.DoubleVar(value=float(self.ui_state["pre_click_delay_seconds"]))
        self.click_delay_var = tk.DoubleVar(value=float(self.ui_state["delay_between_clicks_seconds"]))
        self.click_hold_var = tk.DoubleVar(value=float(self.ui_state["click_hold_seconds"]))
        self.center_hold_var = tk.DoubleVar(value=float(self.ui_state["center_hold_seconds"]))
        self.after_center_delay_var = tk.DoubleVar(value=float(self.ui_state["after_center_delay_seconds"]))
        self.screenshot_settle_var = tk.DoubleVar(value=float(self.ui_state["screenshot_settle_seconds"]))
        self.mouse_check_interval_var = tk.DoubleVar(value=float(self.ui_state["mouse_check_interval_seconds"]))
        self.mouse_move_tolerance_var = tk.DoubleVar(value=float(self.ui_state["mouse_move_tolerance_pixels"]))
        self.detailed_match_min_var = tk.DoubleVar(value=float(self.ui_state["detailed_match_min_score"]))
        self.detailed_match_max_var = tk.DoubleVar(value=float(self.ui_state["detailed_match_max_score"]))
        self.preview_text_var = tk.StringVar(value="Следующий клик не выбран")
        self.log_visible_var = tk.BooleanVar(value=False)
        self.apply_detailed_match_range()

        self.overlay = tk.Toplevel(self.root)
        self.tool_window = tk.Toplevel(self.root)

        self.setup_overlay()
        self.setup_tool_window()
        self.reload_template_combo()
        self.set_capture_size_from_grid()
        self.redraw_overlay()
        self.overlay.withdraw()

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
            "threshold": 0.70,
            "pre_click_delay_seconds": 0.35,
            "delay_between_clicks_seconds": 3.0,
            "click_hold_seconds": 0.05,
            "center_hold_seconds": 1.0,
            "after_center_delay_seconds": 3.0,
            "screenshot_settle_seconds": SCREENSHOT_AFTER_MOUSE_MOVE_DELAY_SECONDS,
            "mouse_check_interval_seconds": 0.03,
            "mouse_move_tolerance_pixels": 45.0,
            "detailed_match_min_score": DETAILED_MATCH_MIN_SCORE,
            "detailed_match_max_score": DETAILED_MATCH_MAX_SCORE,
        }
        if not UI_STATE_PATH.exists():
            return default
        try:
            data = json.loads(UI_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
        return {
            "tool_x": int(data.get("tool_x", default["tool_x"])),
            "tool_y": int(data.get("tool_y", default["tool_y"])),
            "capture_x": float(data.get("capture_x", default["capture_x"])),
            "capture_y": float(data.get("capture_y", default["capture_y"])),
            "threshold": float(data.get("threshold", default["threshold"])),
            "pre_click_delay_seconds": float(data.get("pre_click_delay_seconds", default["pre_click_delay_seconds"])),
            "delay_between_clicks_seconds": float(data.get("delay_between_clicks_seconds", default["delay_between_clicks_seconds"])),
            "click_hold_seconds": float(data.get("click_hold_seconds", default["click_hold_seconds"])),
            "center_hold_seconds": float(data.get("center_hold_seconds", default["center_hold_seconds"])),
            "after_center_delay_seconds": float(data.get("after_center_delay_seconds", default["after_center_delay_seconds"])),
            "screenshot_settle_seconds": float(data.get("screenshot_settle_seconds", default["screenshot_settle_seconds"])),
            "mouse_check_interval_seconds": float(data.get("mouse_check_interval_seconds", default["mouse_check_interval_seconds"])),
            "mouse_move_tolerance_pixels": float(data.get("mouse_move_tolerance_pixels", default["mouse_move_tolerance_pixels"])),
            "detailed_match_min_score": float(data.get("detailed_match_min_score", default["detailed_match_min_score"])),
            "detailed_match_max_score": float(data.get("detailed_match_max_score", default["detailed_match_max_score"])),
        }

    def save_ui_state(self) -> None:
        self.ui_state["threshold"] = float(self.threshold_var.get())
        self.ui_state["pre_click_delay_seconds"] = float(self.pre_click_delay_var.get())
        self.ui_state["delay_between_clicks_seconds"] = float(self.click_delay_var.get())
        self.ui_state["click_hold_seconds"] = float(self.click_hold_var.get())
        self.ui_state["center_hold_seconds"] = float(self.center_hold_var.get())
        self.ui_state["after_center_delay_seconds"] = float(self.after_center_delay_var.get())
        self.ui_state["screenshot_settle_seconds"] = float(self.screenshot_settle_var.get())
        self.ui_state["mouse_check_interval_seconds"] = float(self.mouse_check_interval_var.get())
        self.ui_state["mouse_move_tolerance_pixels"] = float(self.mouse_move_tolerance_var.get())
        self.ui_state["detailed_match_min_score"] = float(self.detailed_match_min_var.get())
        self.ui_state["detailed_match_max_score"] = float(self.detailed_match_max_var.get())
        UI_STATE_PATH.write_text(json.dumps(self.ui_state, ensure_ascii=False, indent=2), encoding="utf-8")

    def migrate_ui_state(self) -> None:
        if int(self.ui_state.get("matcher_version", 1)) >= 2:
            return
        self.ui_state["threshold"] = max(0.70, float(self.ui_state.get("threshold", 0.70)))
        self.ui_state["matcher_version"] = 2

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
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.overlay.bind("<Escape>", lambda _e: self.close_add_capture())

    def setup_tool_window(self) -> None:
        x = self.ui_state["tool_x"]
        y = self.ui_state["tool_y"]
        self.tool_window.title("DBD Bloodweb Bot")
        self.tool_window.attributes("-topmost", True)
        self.tool_window.geometry(f"760x1010+{x}+{y}")
        self.tool_window.minsize(720, 960)
        self.tool_window.protocol("WM_DELETE_WINDOW", self.close)

        root = ttk.Frame(self.tool_window, padding=10)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x", pady=(0, 10))
        ttk.Button(top, textvariable=self.grid_button_var, command=self.toggle_grid).pack(side="left")
        ttk.Label(top, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).pack(side="left", padx=14)
        self.top_stop_button = ttk.Button(top, text="Stop", command=self.stop_auto)
        self.top_stop_button.pack(side="right")
        self.top_stop_button.pack_forget()

        priority_box = ttk.LabelFrame(root, text="Приоритет: выкупается перед выбранным шаблоном", padding=8)
        priority_box.pack(fill="x", pady=(0, 8))
        self.priority_tree = ttk.Treeview(priority_box, show="tree", height=4, selectmode="browse")
        self.priority_tree.pack(side="left", fill="both", expand=True)
        self.priority_tree.bind("<<TreeviewSelect>>", lambda _e: self.on_priority_selected())
        priority_buttons = ttk.Frame(priority_box)
        priority_buttons.pack(side="left", fill="y", padx=(8, 0))
        ttk.Button(priority_buttons, text="Выше", command=lambda: self.move_priority_item(-1)).pack(fill="x")
        ttk.Button(priority_buttons, text="Ниже", command=lambda: self.move_priority_item(1)).pack(fill="x", pady=(4, 0))
        ttk.Button(priority_buttons, text="Переименовать", command=self.rename_priority_item).pack(fill="x", pady=(4, 0))
        ttk.Button(priority_buttons, text="В шаблон", command=self.move_priority_item_to_template).pack(fill="x", pady=(4, 0))
        ttk.Button(priority_buttons, text="Удалить", command=self.remove_priority_item).pack(fill="x", pady=(4, 0))

        template_box = ttk.LabelFrame(root, text="Текущий шаблон", padding=8)
        template_box.pack(fill="x", pady=(0, 8))
        template_row = ttk.Frame(template_box)
        template_row.pack(fill="x")
        self.template_combo = ttk.Combobox(template_row, textvariable=self.template_var, state="readonly")
        self.template_combo.pack(side="left", fill="x", expand=True)
        self.template_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_current_template())
        ttk.Button(template_row, text="Новый", command=self.create_empty_template).pack(side="left", padx=(6, 0))
        ttk.Button(template_row, text="Дублировать", command=self.duplicate_template).pack(side="left", padx=(6, 0))
        ttk.Button(template_row, text="Переименовать", command=self.rename_template).pack(side="left", padx=(6, 0))
        ttk.Button(template_row, text="Удалить", command=self.delete_template).pack(side="left", padx=(6, 0))

        items_box = ttk.LabelFrame(root, text="Элементы шаблона: сверху важнее", padding=8)
        items_box.pack(fill="both", expand=True, pady=(0, 8))
        items_content = ttk.Frame(items_box)
        items_content.pack(fill="both", expand=True)

        left = ttk.Frame(items_content)
        left.pack(side="left", fill="both", expand=True)
        self.items_tree = ttk.Treeview(left, columns=("name",), show="tree", height=12, selectmode="browse")
        self.items_tree.pack(fill="both", expand=True)
        self.items_tree.bind("<<TreeviewSelect>>", lambda _e: self.on_template_item_selected())

        item_buttons = ttk.Frame(left)
        item_buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(item_buttons, text="Выше", command=lambda: self.move_selected_item(-1)).pack(side="left", fill="x", expand=True)
        ttk.Button(item_buttons, text="Ниже", command=lambda: self.move_selected_item(1)).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(item_buttons, text="Переименовать", command=self.rename_selected_item).pack(side="left", fill="x", expand=True)
        ttk.Button(item_buttons, text="Удалить", command=self.remove_selected_item).pack(side="left", fill="x", expand=True, padx=(4, 0))
        ttk.Button(item_buttons, text="В приоритет", command=self.move_selected_item_to_priority).pack(side="left", fill="x", expand=True)

        right = ttk.Frame(items_content)
        right.pack(side="left", fill="y", padx=(10, 0))
        ttk.Label(right, text="Предпросмотр").pack(anchor="w")
        self.selected_canvas = tk.Canvas(right, width=150, height=150, bg="#111111", highlightthickness=1, highlightbackground="#333333")
        self.selected_canvas.pack(pady=(4, 0))

        self.add_area = ttk.Frame(root)
        self.add_area.pack(fill="x", pady=(0, 8))
        self.add_button = ttk.Button(self.add_area, text="Добавить скрин", command=self.open_add_capture)
        self.add_button.pack(fill="x")

        self.add_frame = ttk.LabelFrame(self.add_area, text="Добавление скрина", padding=8)
        add_row = ttk.Frame(self.add_frame)
        add_row.pack(fill="x")
        ttk.Label(add_row, text="Название").pack(side="left")
        ttk.Entry(add_row, textvariable=self.capture_label_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(add_row, text="Сделать скрин", command=self.capture_current_region).pack(side="left")
        ttk.Button(add_row, text="Закрыть добавление", command=self.close_add_capture).pack(side="left", padx=(6, 0))

        recog_box = ttk.LabelFrame(root, text="Распознавание", padding=8)
        recog_box.pack(fill="x", pady=(0, 8))
        ttk.Label(recog_box, text="Уровень доверия").pack(side="left")
        self.threshold_scale = ttk.Scale(
            recog_box,
            from_=0.10,
            to=0.99,
            variable=self.threshold_var,
            command=self.on_threshold_scale,
        )
        self.threshold_scale.pack(side="left", fill="x", expand=True, padx=8)
        threshold_entry = ttk.Entry(recog_box, textvariable=self.threshold_text_var, width=6)
        threshold_entry.pack(side="left")
        threshold_entry.bind("<Return>", lambda _e: self.apply_threshold_entry())
        threshold_entry.bind("<FocusOut>", lambda _e: self.apply_threshold_entry())

        detail_box = ttk.LabelFrame(root, text="Детальная проверка спорных совпадений", padding=8)
        detail_box.pack(fill="x", pady=(0, 8))
        ttk.Label(detail_box, text="От score").pack(side="left")
        detail_min_spin = ttk.Spinbox(
            detail_box,
            textvariable=self.detailed_match_min_var,
            from_=0.0,
            to=1.0,
            increment=0.01,
            width=7,
            command=self.apply_detailed_match_range,
        )
        detail_min_spin.pack(side="left", padx=(6, 12))
        ttk.Label(detail_box, text="До score").pack(side="left")
        detail_max_spin = ttk.Spinbox(
            detail_box,
            textvariable=self.detailed_match_max_var,
            from_=0.0,
            to=1.0,
            increment=0.01,
            width=7,
            command=self.apply_detailed_match_range,
        )
        detail_max_spin.pack(side="left", padx=(6, 0))
        detail_min_spin.bind("<Return>", lambda _e: self.apply_detailed_match_range())
        detail_min_spin.bind("<FocusOut>", lambda _e: self.apply_detailed_match_range())
        detail_max_spin.bind("<Return>", lambda _e: self.apply_detailed_match_range())
        detail_max_spin.bind("<FocusOut>", lambda _e: self.apply_detailed_match_range())

        speed_box = ttk.LabelFrame(root, text="Скорость и таймеры", padding=8)
        speed_box.pack(fill="x", pady=(0, 8))
        speed_box.columnconfigure(1, weight=1)
        speed_box.columnconfigure(3, weight=1)
        ttk.Label(speed_box, text="Перед каждым кликом, сек").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
        pre_click_spin = ttk.Spinbox(
            speed_box,
            textvariable=self.pre_click_delay_var,
            from_=0.0,
            to=5.0,
            increment=0.05,
            width=7,
            command=self.save_speed_settings,
        )
        pre_click_spin.grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(speed_box, text="Пауза между кликами, сек").grid(row=0, column=2, sticky="w", padx=(14, 6), pady=2)
        click_delay_spin = ttk.Spinbox(
            speed_box,
            textvariable=self.click_delay_var,
            from_=0.1,
            to=30.0,
            increment=0.1,
            width=7,
            command=self.save_speed_settings,
        )
        click_delay_spin.grid(row=0, column=3, sticky="w", pady=2)
        ttk.Label(speed_box, text="Удержание обычного клика, сек").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=2)
        click_hold_spin = ttk.Spinbox(
            speed_box,
            textvariable=self.click_hold_var,
            from_=0.01,
            to=2.0,
            increment=0.01,
            width=7,
            command=self.save_speed_settings,
        )
        click_hold_spin.grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(speed_box, text="Удержание клика в центр, сек").grid(row=1, column=2, sticky="w", padx=(14, 6), pady=2)
        center_hold_spin = ttk.Spinbox(
            speed_box,
            textvariable=self.center_hold_var,
            from_=0.1,
            to=10.0,
            increment=0.1,
            width=7,
            command=self.save_speed_settings,
        )
        center_hold_spin.grid(row=1, column=3, sticky="w", pady=2)
        ttk.Label(speed_box, text="После отвода мыши перед скрином, сек").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=2)
        screenshot_settle_spin = ttk.Spinbox(
            speed_box,
            textvariable=self.screenshot_settle_var,
            from_=0.0,
            to=2.0,
            increment=0.05,
            width=7,
            command=self.save_speed_settings,
        )
        screenshot_settle_spin.grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(speed_box, text="Проверка ручного сдвига мыши, сек").grid(row=2, column=2, sticky="w", padx=(14, 6), pady=2)
        mouse_check_spin = ttk.Spinbox(
            speed_box,
            textvariable=self.mouse_check_interval_var,
            from_=0.01,
            to=0.50,
            increment=0.01,
            width=7,
            command=self.save_speed_settings,
        )
        mouse_check_spin.grid(row=2, column=3, sticky="w", pady=2)
        ttk.Label(speed_box, text="После клика в центр до нового скрина, сек").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=2)
        after_center_spin = ttk.Spinbox(
            speed_box,
            textvariable=self.after_center_delay_var,
            from_=0.1,
            to=30.0,
            increment=0.1,
            width=7,
            command=self.save_speed_settings,
        )
        after_center_spin.grid(row=3, column=1, sticky="w", pady=2)
        ttk.Label(speed_box, text="Сдвиг мыши для стопа, пикс").grid(row=3, column=2, sticky="w", padx=(14, 6), pady=2)
        mouse_tolerance_spin = ttk.Spinbox(
            speed_box,
            textvariable=self.mouse_move_tolerance_var,
            from_=10.0,
            to=200.0,
            increment=5.0,
            width=7,
            command=self.save_speed_settings,
        )
        mouse_tolerance_spin.grid(row=3, column=3, sticky="w", pady=2)
        for spinbox in (pre_click_spin, click_delay_spin, click_hold_spin, center_hold_spin, screenshot_settle_spin, mouse_check_spin, after_center_spin, mouse_tolerance_spin):
            spinbox.bind("<Return>", lambda _e: self.save_speed_settings())
            spinbox.bind("<FocusOut>", lambda _e: self.save_speed_settings())

        auto_box = ttk.LabelFrame(root, text="Автоклик", padding=8)
        auto_box.pack(fill="x", pady=(0, 8))
        ttk.Button(auto_box, text="Start", command=self.start_auto).pack(side="left")
        ttk.Button(auto_box, text="Stop", command=self.stop_auto).pack(side="left", padx=6)
        ttk.Button(auto_box, text="Тест", command=self.test_click_queue).pack(side="left")

        queue_box = ttk.LabelFrame(root, text="Очередь кликов", padding=8)
        queue_box.pack(fill="both", expand=False, pady=(0, 8))
        self.queue_list = tk.Listbox(queue_box, height=5)
        self.queue_list.pack(fill="both", expand=True)

        next_box = ttk.LabelFrame(root, text="Следующий клик", padding=8)
        next_box.pack(fill="x", pady=(0, 8))
        self.preview_canvas = tk.Canvas(next_box, width=116, height=116, bg="#111111", highlightthickness=1, highlightbackground="#333333")
        self.preview_canvas.pack(side="left")
        ttk.Label(next_box, textvariable=self.preview_text_var, anchor="w").pack(side="left", fill="x", expand=True, padx=10)
        self.render_next_preview(None, "Следующий клик не выбран", draw_cross=False)

        ttk.Checkbutton(root, text="Показать лог", variable=self.log_visible_var, command=self.toggle_log).pack(anchor="w")
        self.log_frame = ttk.Frame(root)
        self.log_list = tk.Listbox(self.log_frame, height=4)
        self.log_list.pack(fill="both", expand=True)

        self.tool_window.bind("<Configure>", self.on_tool_window_configure)
        self.tool_window.bind("<Escape>", lambda _e: self.close_add_capture())

    def reload_template_combo(self) -> None:
        self.template_refs = []
        names = []
        for index, item in enumerate(self.search_data.get("killer_templates", [])):
            self.template_refs.append(("killer", index))
            names.append(item["name"])
        for index, item in enumerate(self.search_data.get("survivor_templates", [])):
            self.template_refs.append(("survivor", index))
            names.append(item["name"])

        if not names:
            self.search_data["killer_templates"] = [{"name": "default", "killer_id": None, "items": []}]
            self.save_search_data()
            return self.reload_template_combo()

        self.template_combo.configure(values=names)
        if self.template_var.get() not in names:
            self.template_var.set(names[0])
        self.refresh_priority_items()
        self.refresh_current_template()

    def enforce_single_owner_items(self) -> None:
        priority_ids = {item.get("id") for item in self.search_data.get("priority_items", [])}
        changed = False
        for template in self.search_data.get("killer_templates", []):
            original = template.get("items", [])
            filtered = [item for item in original if item.get("id") not in priority_ids]
            if len(filtered) != len(original):
                template["items"] = filtered
                changed = True
        for template in self.search_data.get("survivor_templates", []):
            original = template.get("items", [])
            filtered = [item for item in original if item.get("id") not in priority_ids]
            if len(filtered) != len(original):
                template["items"] = filtered
                changed = True
        if changed:
            self.save_search_data()

    def enrich_search_item_sizes(self) -> None:
        changed = False
        for item in self.iter_search_items():
            changed = self.fill_item_image_metadata(item) or changed
        if changed:
            self.save_search_data()

    def iter_search_items(self):
        for item in self.search_data.get("priority_items", []):
            yield item
        for template in self.search_data.get("killer_templates", []):
            yield from template.get("items", [])
        for template in self.search_data.get("survivor_templates", []):
            yield from template.get("items", [])

    def fill_item_image_metadata(self, item: dict) -> bool:
        image_path = item.get("image_path")
        if not image_path:
            return False
        image = imread_unicode(Path(image_path), -1)
        if image is None:
            return False
        height, width = image.shape[:2]
        metadata = {
            "image_width": int(width),
            "image_height": int(height),
            "match_size": int(self.matcher.default_match_size_for_image(image)),
            "crop_ratio": float(self.matcher.normalization_crop_ratio()),
            "variant_algorithm": self.matcher.variant_algorithm_version(),
        }
        changed = False
        for key, value in metadata.items():
            if item.get(key) != value:
                item[key] = value
                changed = True
        return changed

    def refresh_priority_items(self) -> None:
        self.priority_tree.delete(*self.priority_tree.get_children())
        self.priority_icons.clear()
        for index, item in enumerate(self.search_data.get("priority_items", []), start=1):
            image = self.load_tree_icon(item.get("image_path"))
            self.priority_icons.append(image)
            self.priority_tree.insert("", "end", iid=str(index - 1), text=f"{index}. {item.get('label', 'template')}", image=image)

    def current_template_ref(self) -> tuple[str, int] | None:
        try:
            index = list(self.template_combo["values"]).index(self.template_var.get())
        except ValueError:
            return None
        if 0 <= index < len(self.template_refs):
            return self.template_refs[index]
        return None

    def current_template(self) -> dict | None:
        ref = self.current_template_ref()
        if not ref:
            return None
        section, index = ref
        key = "killer_templates" if section == "killer" else "survivor_templates"
        items = self.search_data.get(key, [])
        if 0 <= index < len(items):
            return items[index]
        return None

    def refresh_current_template(self) -> None:
        self.items_tree.delete(*self.items_tree.get_children())
        self.item_icons.clear()
        template = self.current_template()
        if not template:
            self.render_selected_item_preview()
            return
        for index, item in enumerate(template.get("items", []), start=1):
            image = self.load_tree_icon(item.get("image_path"))
            self.item_icons.append(image)
            self.items_tree.insert("", "end", iid=str(index - 1), text=f"{index}. {item.get('label', 'template')}", image=image)
        self.render_selected_item_preview()

    def load_tree_icon(self, image_path: str | None) -> ImageTk.PhotoImage:
        image = Image.new("RGBA", (28, 28), (22, 22, 22, 255))
        if image_path:
            raw = imread_unicode(Path(image_path), -1)
            if raw is not None:
                pil = self.cv_to_pil(raw)
                pil.thumbnail((24, 24))
                image.alpha_composite(pil, ((28 - pil.width) // 2, (28 - pil.height) // 2))
        return ImageTk.PhotoImage(image.convert("RGB"))

    def template_name_exists(self, name: str) -> bool:
        return any(item["name"] == name for item in self.search_data.get("killer_templates", [])) or any(
            item["name"] == name for item in self.search_data.get("survivor_templates", [])
        )

    def create_empty_template(self) -> None:
        name = simpledialog.askstring("Новый шаблон", "Имя шаблона:", parent=self.tool_window)
        if not name:
            return
        if self.template_name_exists(name):
            self.set_status("Шаблон с таким именем уже есть")
            return
        self.search_data.setdefault("killer_templates", []).append({"name": name, "killer_id": None, "items": []})
        self.save_search_data()
        self.template_var.set(name)
        self.reload_template_combo()

    def duplicate_template(self) -> None:
        template = self.current_template()
        ref = self.current_template_ref()
        if not template or not ref:
            return
        default_name = f"{template['name']}_copy"
        name = simpledialog.askstring("Дублировать шаблон", "Новое имя:", initialvalue=default_name, parent=self.tool_window)
        if not name:
            return
        if self.template_name_exists(name):
            self.set_status("Шаблон с таким именем уже есть")
            return
        clone = json.loads(json.dumps(template))
        clone["name"] = name
        if ref[0] == "killer":
            self.search_data.setdefault("killer_templates", []).append(clone)
        else:
            self.search_data.setdefault("survivor_templates", []).append(clone)
        self.save_search_data()
        self.template_var.set(name)
        self.reload_template_combo()

    def rename_template(self) -> None:
        template = self.current_template()
        if not template:
            return
        name = simpledialog.askstring("Переименовать шаблон", "Новое имя:", initialvalue=template["name"], parent=self.tool_window)
        if not name or name == template["name"]:
            return
        if self.template_name_exists(name):
            self.set_status("Шаблон с таким именем уже есть")
            return
        template["name"] = name
        self.save_search_data()
        self.template_var.set(name)
        self.reload_template_combo()

    def delete_template(self) -> None:
        template = self.current_template()
        ref = self.current_template_ref()
        if not template or not ref:
            return
        if not messagebox.askyesno("Удалить шаблон", f"Удалить шаблон '{template['name']}'?", parent=self.tool_window):
            return
        key = "killer_templates" if ref[0] == "killer" else "survivor_templates"
        self.search_data[key].pop(ref[1])
        if not self.search_data.get("killer_templates") and not self.search_data.get("survivor_templates"):
            self.search_data["killer_templates"] = [{"name": "default", "killer_id": None, "items": []}]
        self.save_search_data()
        self.reload_template_combo()

    def selected_item_index(self) -> int | None:
        selection = self.items_tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def selected_priority_index(self) -> int | None:
        selection = self.priority_tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def on_priority_selected(self) -> None:
        if self.selection_syncing:
            return
        if self.priority_tree.selection():
            self.selection_syncing = True
            self.items_tree.selection_remove(self.items_tree.selection())
            self.selection_syncing = False
        self.render_priority_item_preview()

    def on_template_item_selected(self) -> None:
        if self.selection_syncing:
            return
        if self.items_tree.selection():
            self.selection_syncing = True
            self.priority_tree.selection_remove(self.priority_tree.selection())
            self.selection_syncing = False
        self.render_selected_item_preview()

    def render_priority_item_preview(self) -> None:
        self.selected_canvas.delete("all")
        self.selected_canvas.create_rectangle(0, 0, 150, 150, fill="#111111", outline="")
        index = self.selected_priority_index()
        items = self.search_data.get("priority_items", [])
        if index is None or index >= len(items):
            self.selected_canvas.create_text(75, 75, text="Нет", fill="#888888", font=("Segoe UI", 16, "bold"))
            return
        self.draw_image_on_canvas(self.selected_canvas, items[index].get("image_path"), 150, 150, "?", "selected")

    def move_priority_item(self, direction: int) -> None:
        items = self.search_data.setdefault("priority_items", [])
        index = self.selected_priority_index()
        if index is None:
            return
        target = index + direction
        if target < 0 or target >= len(items):
            return
        items[index], items[target] = items[target], items[index]
        self.save_search_data()
        self.refresh_priority_items()
        self.priority_tree.selection_set(str(target))
        self.priority_tree.focus(str(target))
        self.render_priority_item_preview()

    def rename_priority_item(self) -> None:
        items = self.search_data.setdefault("priority_items", [])
        index = self.selected_priority_index()
        if index is None or index >= len(items):
            return
        old_name = items[index].get("label", "")
        name = simpledialog.askstring("Переименовать приоритет", "Новое имя:", initialvalue=old_name, parent=self.tool_window)
        if not name:
            return
        items[index]["label"] = name
        self.save_search_data()
        self.refresh_priority_items()
        self.priority_tree.selection_set(str(index))
        self.render_priority_item_preview()

    def remove_priority_item(self) -> None:
        items = self.search_data.setdefault("priority_items", [])
        index = self.selected_priority_index()
        if index is None or index >= len(items):
            return
        item = items[index]
        if not messagebox.askyesno("Удалить приоритет", f"Удалить '{item.get('label', 'элемент')}' из приоритета?", parent=self.tool_window):
            return
        items.pop(index)
        self.delete_item_file_if_unreferenced(item)
        self.save_search_data()
        self.refresh_priority_items()
        self.render_priority_item_preview()

    def move_priority_item_to_template(self) -> None:
        template = self.current_template()
        priority_items = self.search_data.setdefault("priority_items", [])
        index = self.selected_priority_index()
        if not template or index is None or index >= len(priority_items):
            return
        item = priority_items.pop(index)
        template_items = template.setdefault("items", [])
        if any(existing.get("id") == item.get("id") for existing in template_items):
            self.set_status("Этот элемент уже есть в выбранном шаблоне")
            priority_items.insert(index, item)
            return
        template_items.append(item)
        self.save_search_data()
        self.refresh_priority_items()
        self.refresh_current_template()
        target = len(template_items) - 1
        self.items_tree.selection_set(str(target))
        self.render_selected_item_preview()
        self.set_status("Перемещено в шаблон")

    def move_selected_item_to_priority(self) -> None:
        template = self.current_template()
        index = self.selected_item_index()
        if not template or index is None:
            return
        items = template.get("items", [])
        if index >= len(items):
            return
        item = items.pop(index)
        priority_items = self.search_data.setdefault("priority_items", [])
        if any(existing.get("id") == item.get("id") for existing in priority_items):
            self.set_status("Этот элемент уже есть в приоритете")
            items.insert(index, item)
            return
        priority_items.append(item)
        self.save_search_data()
        self.refresh_priority_items()
        self.refresh_current_template()
        self.priority_tree.selection_set(str(len(priority_items) - 1))
        self.render_priority_item_preview()
        self.set_status("Перемещено в приоритет")

    def move_selected_item(self, direction: int) -> None:
        template = self.current_template()
        index = self.selected_item_index()
        if not template or index is None:
            return
        items = template.get("items", [])
        target = index + direction
        if target < 0 or target >= len(items):
            return
        items[index], items[target] = items[target], items[index]
        self.save_search_data()
        self.refresh_current_template()
        self.items_tree.selection_set(str(target))
        self.items_tree.focus(str(target))

    def rename_selected_item(self) -> None:
        template = self.current_template()
        index = self.selected_item_index()
        if not template or index is None:
            return
        items = template.get("items", [])
        if index >= len(items):
            return
        old_name = items[index].get("label", "")
        name = simpledialog.askstring("Переименовать элемент", "Новое имя:", initialvalue=old_name, parent=self.tool_window)
        if not name:
            return
        items[index]["label"] = name
        self.save_search_data()
        self.refresh_current_template()
        self.items_tree.selection_set(str(index))
        self.render_selected_item_preview()

    def remove_selected_item(self) -> None:
        template = self.current_template()
        index = self.selected_item_index()
        if not template or index is None:
            return
        items = template.get("items", [])
        if index >= len(items):
            return
        item = items[index]
        if not messagebox.askyesno("Удалить элемент", f"Удалить '{item.get('label', 'элемент')}'?", parent=self.tool_window):
            return
        items.pop(index)
        self.delete_item_file_if_unreferenced(item)
        self.save_search_data()
        self.refresh_current_template()

    def render_selected_item_preview(self) -> None:
        self.selected_canvas.delete("all")
        self.selected_canvas.create_rectangle(0, 0, 150, 150, fill="#111111", outline="")
        template = self.current_template()
        index = self.selected_item_index()
        if not template or index is None:
            self.selected_canvas.create_text(75, 75, text="Нет", fill="#888888", font=("Segoe UI", 16, "bold"))
            return
        items = template.get("items", [])
        if index >= len(items):
            return
        self.draw_image_on_canvas(self.selected_canvas, items[index].get("image_path"), 150, 150, "?", "selected")

    def open_add_capture(self) -> None:
        self.adding_capture = True
        self.set_capture_size_from_grid()
        self.add_button.pack_forget()
        self.add_frame.pack(fill="x")
        self.show_overlay_if_needed()
        self.redraw_overlay()

    def close_add_capture(self) -> None:
        if not self.adding_capture:
            return
        self.adding_capture = False
        self.capture_label_var.set("")
        self.add_frame.pack_forget()
        self.add_button.pack(fill="x")
        self.hide_overlay_if_unused()
        self.redraw_overlay()

    def set_capture_size_from_grid(self) -> None:
        size = max(16.0, float(self.template.roi_size) * CAPTURE_BOX_ROI_RATIO)
        self.ui_state["capture_w"] = size
        self.ui_state["capture_h"] = size

    def toggle_grid(self) -> None:
        self.grid_visible = not self.grid_visible
        self.grid_button_var.set("Скрыть сетку" if self.grid_visible else "Показать сетку")
        if self.grid_visible:
            self.show_overlay_if_needed()
        else:
            self.hide_overlay_if_unused()
        self.redraw_overlay()

    def show_overlay_if_needed(self) -> None:
        if self.grid_visible or self.adding_capture:
            self.overlay.deiconify()
            self.overlay.lift()
            self.tool_window.lift()
            self.tool_window.attributes("-topmost", True)

    def hide_overlay_if_unused(self) -> None:
        if not self.grid_visible and not self.adding_capture:
            self.overlay.withdraw()

    def on_tool_window_configure(self, _event: tk.Event) -> None:
        if self.tool_window.state() == "normal":
            self.ui_state["tool_x"] = self.tool_window.winfo_x()
            self.ui_state["tool_y"] = self.tool_window.winfo_y()
            self.save_ui_state()

    def redraw_overlay(self) -> None:
        self.canvas.delete("all")
        if self.grid_visible:
            self.draw_grid()
        if self.adding_capture:
            self.draw_capture_box()

    def draw_grid(self) -> None:
        for ring, spec in RING_SPECS.items():
            points = [self.node_position(ring, index) for index in range(spec["count"])]
            for index, (x1, y1) in enumerate(points):
                x2, y2 = points[(index + 1) % len(points)]
                self.canvas.create_line(x1, y1, x2, y2, fill="#c4a35a", width=2)
        for ring, spec in RING_SPECS.items():
            radius = getattr(self.template, f"ring{ring}_radius")
            self.canvas.create_oval(
                self.template.center_x - radius,
                self.template.center_y - radius,
                self.template.center_x + radius,
                self.template.center_y + radius,
                outline=spec["color"],
                width=2,
                dash=(6, 4),
            )
            for index in range(spec["count"]):
                x, y = self.node_position(ring, index)
                half = self.template.roi_size / 2.0
                self.canvas.create_rectangle(x - half, y - half, x + half, y + half, outline=spec["color"], width=2)
        x = self.template.center_x
        y = self.template.center_y
        self.canvas.create_oval(x - 34, y - 34, x + 34, y + 34, fill="#ff3333", outline="#210000", width=4)
        self.canvas.create_oval(x - 12, y - 12, x + 12, y + 12, fill="#210000", outline="")
        self.draw_grid_resize_handles()

    def draw_grid_resize_handles(self) -> None:
        radius = self.template.ring3_radius
        size = 14
        for x, y in (
            (self.template.center_x + radius, self.template.center_y),
            (self.template.center_x - radius, self.template.center_y),
            (self.template.center_x, self.template.center_y + radius),
            (self.template.center_x, self.template.center_y - radius),
        ):
            self.canvas.create_rectangle(x - size / 2, y - size / 2, x + size / 2, y + size / 2, fill="#c4a35a", outline="#111111", width=1)

    def draw_capture_box(self) -> None:
        self.set_capture_size_from_grid()
        x = self.ui_state["capture_x"]
        y = self.ui_state["capture_y"]
        w = self.ui_state["capture_w"]
        h = self.ui_state["capture_h"]
        self.canvas.create_rectangle(x, y, x + w, y + h, outline="#ffe45c", width=3)
        handle = min(18.0, max(8.0, w / 5.0))
        self.canvas.create_rectangle(x + w - handle, y, x + w, y + handle, fill="#ffe45c", outline="#111111", width=1)
        self.canvas.create_text(x + 4, y - 16, text="Скрин", fill="#ffe45c", anchor="nw", font=("Segoe UI", 10, "bold"))

    def node_position(self, ring: int, index: int) -> tuple[float, float]:
        spec = RING_SPECS[ring]
        radius = getattr(self.template, f"ring{ring}_radius")
        angle_deg = spec["start_deg"] + index * (360.0 / spec["count"]) + self.template.rotation_deg
        angle = math.radians(angle_deg)
        return self.template.center_x + math.cos(angle) * radius, self.template.center_y + math.sin(angle) * radius

    def on_left_press(self, event: tk.Event) -> None:
        if self.adding_capture and self.hit_capture_box(event.x, event.y):
            self.capture_drag_data = (event.x, event.y, self.ui_state["capture_x"], self.ui_state["capture_y"])
            return
        if self.grid_visible and self.hit_grid_resize_edge(event.x, event.y):
            distance = max(1.0, math.hypot(event.x - self.template.center_x, event.y - self.template.center_y))
            self.grid_resize_data = (
                distance,
                self.template.ring1_radius,
                self.template.ring2_radius,
                self.template.ring3_radius,
                self.template.roi_size,
            )
            return
        if self.grid_visible and math.hypot(event.x - self.template.center_x, event.y - self.template.center_y) <= 60:
            self.grid_drag_data = (event.x, event.y, self.template.center_x, self.template.center_y)

    def on_left_drag(self, event: tk.Event) -> None:
        if self.capture_drag_data:
            start_x, start_y, box_x, box_y = self.capture_drag_data
            self.ui_state["capture_x"] = max(0.0, box_x + (event.x - start_x))
            self.ui_state["capture_y"] = max(0.0, box_y + (event.y - start_y))
            self.save_ui_state()
            self.redraw_overlay()
            return

        if self.grid_resize_data:
            start_distance, ring1, ring2, ring3, roi_size = self.grid_resize_data
            current_distance = max(1.0, math.hypot(event.x - self.template.center_x, event.y - self.template.center_y))
            factor = max(0.2, min(5.0, current_distance / start_distance))
            self.template.ring1_radius = max(20.0, ring1 * factor)
            self.template.ring2_radius = max(40.0, ring2 * factor)
            self.template.ring3_radius = max(60.0, ring3 * factor)
            self.template.roi_size = max(16.0, roi_size * factor)
            self.set_capture_size_from_grid()
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

    def on_mouse_wheel(self, event: tk.Event) -> None:
        if not self.grid_visible:
            return
        factor = 1.05 if event.delta > 0 else (1.0 / 1.05)
        self.template.ring1_radius = max(20.0, self.template.ring1_radius * factor)
        self.template.ring2_radius = max(40.0, self.template.ring2_radius * factor)
        self.template.ring3_radius = max(60.0, self.template.ring3_radius * factor)
        self.template.roi_size = max(16.0, self.template.roi_size * factor)
        self.set_capture_size_from_grid()
        self.save_grid_template(self.template)
        self.redraw_overlay()

    def hit_capture_box(self, x: float, y: float) -> bool:
        padding = 24.0
        return (
            self.ui_state["capture_x"] - padding <= x <= self.ui_state["capture_x"] + self.ui_state["capture_w"] + padding
            and self.ui_state["capture_y"] - padding <= y <= self.ui_state["capture_y"] + self.ui_state["capture_h"] + padding
        )

    def hit_grid_resize_edge(self, x: float, y: float) -> bool:
        distance = math.hypot(x - self.template.center_x, y - self.template.center_y)
        return abs(distance - self.template.ring3_radius) <= 45.0

    def capture_current_region(self) -> None:
        label = self.capture_label_var.get().strip()
        template = self.current_template()
        if not template:
            self.set_status("Шаблон не выбран")
            return
        if not label:
            self.set_status("Введите название")
            return

        overlay_was_needed = self.grid_visible or self.adding_capture
        self.overlay.withdraw()
        self.tool_window.withdraw()
        self.root.update_idletasks()
        self.park_mouse_for_screenshot()
        image, _ = self.capture_service.capture_primary_monitor()
        x = int(round(self.ui_state["capture_x"]))
        y = int(round(self.ui_state["capture_y"]))
        w = int(round(self.ui_state["capture_w"]))
        h = int(round(self.ui_state["capture_h"]))
        crop = image[max(0, y) : max(0, y) + max(1, h), max(0, x) : max(0, x) + max(1, w)]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        image_path = self.search_template_repo.image_dir / f"{timestamp}.png"
        success, encoded = cv2_imencode_png(crop)
        if success:
            image_path.write_bytes(encoded)
            self.matcher.ensure_template_variant_files(image_path)
            template.setdefault("items", []).append(
                {
                    "id": image_path.stem,
                    "label": label,
                    "image_path": str(image_path),
                    "image_width": int(crop.shape[1]),
                    "image_height": int(crop.shape[0]),
                    "match_size": int(self.matcher.default_match_size_for_image(crop)),
                    "capture_roi_size": float(self.template.roi_size),
                    "crop_ratio": float(self.matcher.normalization_crop_ratio()),
                    "variant_algorithm": self.matcher.variant_algorithm_version(),
                }
            )
            self.save_search_data()
            self.capture_label_var.set("")
            self.refresh_current_template()
            self.set_status(f"Сохранено: {label}")
            self.add_log(f"Добавлен скрин: {label}")
        else:
            self.set_status("Не удалось сохранить скрин")
        self.tool_window.deiconify()
        self.tool_window.attributes("-topmost", True)
        if overlay_was_needed:
            self.overlay.deiconify()
            self.overlay.lift()
            self.tool_window.lift()
            self.tool_window.attributes("-topmost", True)
        self.redraw_overlay()

    def on_threshold_scale(self, _value: str) -> None:
        self.threshold_text_var.set(f"{float(self.threshold_var.get()):.2f}")
        self.save_ui_state()

    def apply_threshold_entry(self) -> None:
        try:
            value = float(self.threshold_text_var.get().replace(",", "."))
        except ValueError:
            value = float(self.threshold_var.get())
        value = max(0.10, min(0.99, value))
        self.threshold_var.set(value)
        self.threshold_text_var.set(f"{value:.2f}")
        self.save_ui_state()

    def apply_detailed_match_range(self) -> tuple[float, float]:
        minimum = self.clamped_float(self.detailed_match_min_var, DETAILED_MATCH_MIN_SCORE, 0.0, 1.0)
        maximum = self.clamped_float(self.detailed_match_max_var, DETAILED_MATCH_MAX_SCORE, 0.0, 1.0)
        if minimum > maximum:
            minimum, maximum = maximum, minimum
        self.detailed_match_min_var.set(minimum)
        self.detailed_match_max_var.set(maximum)
        self.save_ui_state()
        return minimum, maximum

    def save_speed_settings(self) -> None:
        self.pre_click_delay_var.set(self.clamped_float(self.pre_click_delay_var, 0.35, 0.0, 5.0))
        self.click_delay_var.set(self.clamped_float(self.click_delay_var, 3.0, 0.1, 30.0))
        self.click_hold_var.set(self.clamped_float(self.click_hold_var, 0.05, 0.01, 2.0))
        self.center_hold_var.set(self.clamped_float(self.center_hold_var, 1.0, 0.1, 10.0))
        self.after_center_delay_var.set(self.clamped_float(self.after_center_delay_var, 3.0, 0.1, 30.0))
        self.screenshot_settle_var.set(self.clamped_float(self.screenshot_settle_var, SCREENSHOT_AFTER_MOUSE_MOVE_DELAY_SECONDS, 0.0, 2.0))
        self.mouse_check_interval_var.set(self.clamped_float(self.mouse_check_interval_var, 0.03, 0.01, 0.50))
        self.mouse_move_tolerance_var.set(self.clamped_float(self.mouse_move_tolerance_var, 45.0, 10.0, 200.0))
        self.apply_detailed_match_range()
        self.save_ui_state()

    def clamped_float(self, variable: tk.DoubleVar, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(variable.get())
        except (tk.TclError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    def save_grid_template(self, template: GridTemplate) -> None:
        payload = {"schema_version": 2, "description": "Manual Bloodweb grid calibration templates.", "templates": [asdict(template)]}
        (ROOT / "db" / "grid_templates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_search_data(self) -> None:
        self.search_template_repo.save(self.search_data)

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

    def test_click_queue(self) -> None:
        self.apply_threshold_entry()
        self.save_speed_settings()
        self.set_status("Тест")
        self.add_log("Тест: построение очереди")
        detections = self.build_click_queue_from_screenshot()
        self.render_click_queue(detections)
        if not self.build_search_items():
            self.set_status("Нет элементов для поиска")
            return
        if detections:
            first = detections[0]
            self.render_next_preview(first["image_path"], f"Следующий клик: {first['label']}")
            self.set_status("Готово")
        else:
            self.render_next_preview(None, "Следующий клик: центр", draw_cross=True)
            self.set_status("Готово")

    def build_click_queue_from_screenshot(self) -> list[dict]:
        items = self.build_search_items()
        if not items:
            self.render_next_preview(None, "Следующий клик не выбран", draw_cross=False)
            return []
        image, _ = self.capture_clean_screen()
        rois = build_rois(self.template, image.shape[1], image.shape[0])
        return self.detect_in_rois(image, rois, items)

    def render_click_queue(self, detections: list[dict]) -> None:
        self.queue_list.delete(0, "end")
        if not detections:
            self.queue_list.insert("end", "1. центр")
            return
        for index, detection in enumerate(detections, start=1):
            self.queue_list.insert(
                "end",
                f"{index}. {detection['label']} | score {detection['score']:.2f} | {detection['node_id']}",
            )
        self.queue_list.insert("end", f"{len(detections) + 1}. центр")

    def capture_clean_screen(self):
        self.root.update_idletasks()
        self.capture_exclusion_rect = self.current_tool_window_rect()
        overlay_was_needed = self.grid_visible or self.adding_capture
        self.overlay.withdraw()
        self.root.update_idletasks()
        self.park_mouse_for_screenshot()
        image, meta = self.capture_service.capture_primary_monitor()
        self.tool_window.attributes("-topmost", True)
        if overlay_was_needed:
            self.overlay.deiconify()
            self.overlay.lift()
            self.tool_window.lift()
            self.tool_window.attributes("-topmost", True)
        return image, meta

    def park_mouse_for_screenshot(self) -> None:
        self.run_programmatic_mouse_action(
            SCREENSHOT_MOUSE_PARKING_POSITION,
            lambda: self.mouse_controller.move_to(*SCREENSHOT_MOUSE_PARKING_POSITION),
        )
        self.root.update_idletasks()
        time.sleep(self.clamped_float(self.screenshot_settle_var, SCREENSHOT_AFTER_MOUSE_MOVE_DELAY_SECONDS, 0.0, 2.0))

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

    def current_tool_window_rect(self) -> tuple[int, int, int, int] | None:
        if not self.tool_window.winfo_viewable():
            return None
        x1 = int(self.tool_window.winfo_rootx())
        y1 = int(self.tool_window.winfo_rooty())
        x2 = x1 + int(self.tool_window.winfo_width())
        y2 = y1 + int(self.tool_window.winfo_height())
        return x1, y1, x2, y2

    def start_auto(self) -> None:
        if self.auto_thread and self.auto_thread.is_alive():
            return
        self.apply_threshold_entry()
        self.save_speed_settings()
        items = self.build_search_items()
        if not items:
            self.set_status("Нет элементов для поиска")
            return
        self.stop_requested = False
        self.mouse_stop_notified = False
        self.set_expected_mouse_position(self.mouse_controller.mouse.position)
        self.status_var.set("Работает")
        self.top_stop_button.pack(side="right")
        self.overlay.withdraw()
        self.start_mouse_monitor()
        self.auto_thread = threading.Thread(target=self.auto_loop, daemon=True)
        self.auto_thread.start()
        self.add_log("Start")

    def stop_auto(self) -> None:
        self.stop_requested = True
        self.mouse_stop_notified = True
        self.status_var.set("Готово")
        self.top_stop_button.pack_forget()
        if self.grid_visible or self.adding_capture:
            self.overlay.deiconify()
            self.overlay.lift()
            self.tool_window.lift()
            self.tool_window.attributes("-topmost", True)
        self.add_log("Stop")

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

            image, _ = self.capture_clean_screen_threadsafe()
            rois = build_rois(self.template, image.shape[1], image.shape[0])
            detections = self.detect_in_rois(image, rois, items)
            if self.stop_requested:
                return
            self.root.after(0, lambda current=detections: self.render_click_queue(current))
            if not detections:
                center = (int(round(self.template.center_x)), int(round(self.template.center_y)))
                self.after_preview(None, "Следующий клик: центр", True)
                self.after_status("Работает")
                if not self.click_center_and_wait(center, self.expected_mouse_position or expected_position):
                    return
                expected_position = center
                continue

            for detection in detections:
                if self.stop_requested:
                    self.after_stop("Готово")
                    return
                target = (int(round(detection["x"])), int(round(detection["y"])))
                self.after_preview(detection["image_path"], f"Следующий клик: {detection['label']}", False)
                self.after_status("Работает")
                if not self.sleep_with_mouse_check(
                    self.clamped_float(self.pre_click_delay_var, 0.35, 0.0, 5.0),
                    self.expected_mouse_position or expected_position,
                ):
                    return
                expected_position = self.run_programmatic_mouse_action(
                    target,
                    lambda current_target=target: self.mouse_controller.click(
                        current_target[0],
                        current_target[1],
                        self.clamped_float(self.click_hold_var, 0.05, 0.01, 2.0),
                    ),
                )
                if not self.sleep_with_mouse_check(self.clamped_float(self.click_delay_var, 3.0, 0.1, 30.0), expected_position):
                    return
            center = (int(round(self.template.center_x)), int(round(self.template.center_y)))
            self.after_preview(None, "Следующий клик: центр", True)
            if not self.click_center_and_wait(center, self.expected_mouse_position or expected_position):
                return
            expected_position = center

    def click_center_and_wait(self, center: tuple[int, int], current_position: tuple[int, int]) -> bool:
        if not self.sleep_with_mouse_check(self.clamped_float(self.pre_click_delay_var, 0.35, 0.0, 5.0), current_position):
            return False
        expected_position = self.run_programmatic_mouse_action(
            center,
            lambda: self.mouse_controller.hold_click(center[0], center[1], self.clamped_float(self.center_hold_var, 1.0, 0.1, 10.0)),
        )
        return self.sleep_with_mouse_check(self.clamped_float(self.after_center_delay_var, 3.0, 0.1, 30.0), expected_position)

    def detect_in_rois(self, image, rois, items: list[dict]) -> list[dict]:
        ranked = {item["id"]: index for index, item in enumerate(items)}
        best_by_item: dict[str, dict] = {}
        prepared_items = self.matcher.prepare_items(items)
        threshold = float(self.threshold_var.get())
        detail_min, detail_max = self.apply_detailed_match_range()
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
                if not detail["detail_passed"]:
                    continue
            if len(candidates) > 1 and best["score"] - second < MATCH_MARGIN_THRESHOLD:
                continue
            match = {
                "id": best["id"],
                "label": best["label"],
                "image_path": best["image_path"],
                "score": best["score"],
                "margin": best["score"] - second,
                "node_id": roi.node_id,
                "x": roi.center_x,
                "y": roi.center_y,
                "distance": roi.distance_from_center,
                "rank": ranked.get(best["id"], 10_000),
            }
            previous = best_by_item.get(best["id"])
            if previous is None or (match["distance"], match["score"]) > (previous["distance"], previous["score"]):
                best_by_item[best["id"]] = match
        matches = list(best_by_item.values())
        matches.sort(key=lambda item: (item["rank"], -item["distance"], -item["score"]))
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

    def sleep_with_mouse_check(self, seconds: float, expected_position: tuple[int, int]) -> bool:
        self.set_expected_mouse_position(expected_position)
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.stop_requested:
                return False
            if self.mouse_moved_by_user(expected_position):
                self.stop_after_mouse_move()
                return False
            time.sleep(self.clamped_float(self.mouse_check_interval_var, 0.03, 0.01, 0.50))
        return True

    def mouse_moved_by_user(self, expected_position: tuple[int, int], tolerance: float | None = None) -> bool:
        if self.programmatic_mouse_action_active:
            return False
        if time.monotonic() < self.mouse_monitor_paused_until:
            return False
        if tolerance is None:
            tolerance = self.clamped_float(self.mouse_move_tolerance_var, 45.0, 10.0, 200.0)
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
            if self.programmatic_mouse_action_active:
                time.sleep(self.clamped_float(self.mouse_check_interval_var, 0.03, 0.01, 0.50))
                continue
            if time.monotonic() < self.mouse_monitor_paused_until:
                time.sleep(self.clamped_float(self.mouse_check_interval_var, 0.03, 0.01, 0.50))
                continue
            expected = self.expected_mouse_position
            if expected is not None and self.mouse_moved_by_user(expected):
                self.stop_after_mouse_move()
                return
            time.sleep(self.clamped_float(self.mouse_check_interval_var, 0.03, 0.01, 0.50))

    def stop_after_mouse_move(self) -> None:
        if self.mouse_stop_notified:
            return
        self.mouse_stop_notified = True
        self.stop_requested = True
        self.after_stop("Пауза: мышь сдвинули")

    def after_status(self, text: str) -> None:
        self.root.after(0, lambda: self.set_status(text))

    def after_preview(self, image_path: str | None, text: str, draw_cross: bool) -> None:
        self.root.after(0, lambda: self.render_next_preview(image_path, text, draw_cross=draw_cross))

    def after_stop(self, text: str) -> None:
        def callback() -> None:
            if self.grid_visible or self.adding_capture:
                self.overlay.deiconify()
                self.overlay.lift()
                self.tool_window.lift()
                self.tool_window.attributes("-topmost", True)
            self.set_status(text)
            self.top_stop_button.pack_forget()
            self.stop_requested = True

        self.root.after(0, callback)

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def render_next_preview(self, image_path: str | None, text: str, draw_cross: bool = False) -> None:
        self.preview_canvas.delete("all")
        self.preview_canvas.create_rectangle(0, 0, 116, 116, fill="#111111", outline="")
        self.preview_text_var.set(text)
        if not image_path:
            if draw_cross:
                self.preview_canvas.create_text(58, 58, text="X", fill="#ff4444", font=("Segoe UI", 44, "bold"))
            return
        self.draw_image_on_canvas(self.preview_canvas, image_path, 116, 116, "?", "next")

    def draw_image_on_canvas(self, canvas: tk.Canvas, image_path: str | None, width: int, height: int, fallback: str, target: str) -> None:
        if not image_path:
            canvas.create_text(width // 2, height // 2, text=fallback, fill="#ffffff", font=("Segoe UI", 30, "bold"))
            return
        image = imread_unicode(Path(image_path), -1)
        if image is None:
            canvas.create_text(width // 2, height // 2, text=fallback, fill="#ffffff", font=("Segoe UI", 30, "bold"))
            return
        pil = self.cv_to_pil(image)
        background = Image.new("RGBA", (width, height), (17, 17, 17, 255))
        pil.thumbnail((width - 16, height - 16))
        background.alpha_composite(pil, ((width - pil.width) // 2, (height - pil.height) // 2))
        ref = ImageTk.PhotoImage(background.convert("RGB"))
        if target == "selected":
            self.selected_preview_ref = ref
        else:
            self.next_preview_ref = ref
        canvas.create_image(width // 2, height // 2, image=ref)

    def cv_to_pil(self, image):
        if len(image.shape) == 2:
            return Image.fromarray(image).convert("RGBA")
        if image.shape[2] == 4:
            rgba = image[:, :, [2, 1, 0, 3]]
            return Image.fromarray(rgba, "RGBA")
        rgb = image[:, :, ::-1]
        return Image.fromarray(rgb, "RGB").convert("RGBA")

    def delete_item_file_if_unreferenced(self, item: dict) -> None:
        image_path = item.get("image_path")
        if not image_path or self.image_path_is_referenced(image_path):
            return
        path = Path(image_path)
        if path.exists():
            path.unlink()
        variant_dir = self.matcher.variant_dir_for(path)
        if variant_dir.exists():
            for variant_file in variant_dir.glob("*"):
                if variant_file.is_file():
                    variant_file.unlink()
            try:
                variant_dir.rmdir()
            except OSError:
                pass

    def image_path_is_referenced(self, image_path: str) -> bool:
        target = str(Path(image_path))
        for item in self.search_data.get("priority_items", []):
            if str(Path(item.get("image_path", ""))) == target:
                return True
        for template in self.search_data.get("killer_templates", []):
            for item in template.get("items", []):
                if str(Path(item.get("image_path", ""))) == target:
                    return True
        for template in self.search_data.get("survivor_templates", []):
            for item in template.get("items", []):
                if str(Path(item.get("image_path", ""))) == target:
                    return True
        return False

    def toggle_log(self) -> None:
        if self.log_visible_var.get():
            self.log_frame.pack(fill="both", expand=False, pady=(4, 0))
        else:
            self.log_frame.pack_forget()

    def add_log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_list.insert(0, f"{stamp}  {text}")
        while self.log_list.size() > 50:
            self.log_list.delete("end")

    def close(self) -> None:
        self.stop_requested = True
        self.save_grid_template(self.template)
        self.save_search_data()
        self.save_ui_state()
        self.overlay.destroy()
        self.tool_window.destroy()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def cv2_imencode_png(image) -> tuple[bool, bytes]:
    import cv2

    ok, encoded = cv2.imencode(".png", image)
    return bool(ok), encoded.tobytes() if ok else b""


def main() -> None:
    OverlayApp().run()

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class GridTemplate:
    name: str
    screenshot: str
    image_size: list[int] | None
    center_x: float
    center_y: float
    ring1_radius: float
    ring2_radius: float
    ring3_radius: float
    rotation_deg: float
    roi_size: float


@dataclass
class IconRecord:
    id: str
    type: str
    side: str
    ru_name: str | None
    en_name: str | None
    asset_path: Path
    sample_paths: list[Path]

    @property
    def display_name(self) -> str:
        return self.ru_name or self.en_name or self.id


@dataclass
class ProfileSettings:
    click_center_if_not_found: bool = True
    click_center_after_iteration: bool = True
    ask_on_low_confidence: bool = False
    stop_if_mouse_moved: bool = False
    click_delay_sec: float = 3.0
    center_hold_sec: float = 1.0
    match_threshold: float = 0.58
    screenshot_mouse_parking_position: list[int] = field(default_factory=lambda: [0, 0])
    screenshot_after_mouse_move_delay_seconds: float = 0.2


@dataclass
class PriorityProfile:
    profile_name: str
    side: str
    character: str | None
    tiers: dict[str, list[str]]
    settings: ProfileSettings = field(default_factory=ProfileSettings)

    def desired_icon_ids(self) -> list[str]:
        result: list[str] = []
        for tier_name in ("tier1", "tier2", "tier3", "tier4", "tier5"):
            result.extend(self.tiers.get(tier_name, []))
        return list(dict.fromkeys(result))

    def tier_for_icon(self, icon_id: str) -> int | None:
        for index, tier_name in enumerate(("tier1", "tier2", "tier3", "tier4", "tier5"), start=1):
            if icon_id in self.tiers.get(tier_name, []):
                return index
        return None


@dataclass
class NodeROI:
    node_id: str
    ring: int
    index: int
    angle_deg: float
    center_x: float
    center_y: float
    x1: int
    y1: int
    x2: int
    y2: int
    distance_from_center: float


@dataclass
class MatchCandidate:
    icon_id: str
    display_name: str
    score: float


@dataclass
class Detection:
    roi: NodeROI
    icon_id: str
    display_name: str
    score: float
    candidates: list[MatchCandidate]


@dataclass
class PlannedTarget:
    roi: NodeROI
    icon_id: str
    display_name: str
    score: float
    tier: int
    click_x: int
    click_y: int
    reason: str


@dataclass
class StepResult:
    image: np.ndarray
    rois: list[NodeROI]
    detections: list[Detection]
    click_plan: list[PlannedTarget]
    used_profile: PriorityProfile
    used_template: GridTemplate
    fallback_center: tuple[int, int] | None
    source_name: str

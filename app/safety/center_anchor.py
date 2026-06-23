from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import cv2

from app.models import NodeROI
from app.vision.image_io import imread_unicode
from app.vision.snippet_matcher import NORMALIZATION_CROP_RATIO, SnippetMatcher, TONE_VARIANT_MODES


CENTER_UNCONFIGURED = "CENTER_UNCONFIGURED"
CENTER_CONFIRMED = "CENTER_CONFIRMED"
CENTER_RECHECKING = "CENTER_RECHECKING"
CENTER_NOT_CONFIRMED = "CENTER_NOT_CONFIRMED"
CENTER_STATES = {
    CENTER_UNCONFIGURED,
    CENTER_CONFIRMED,
    CENTER_RECHECKING,
    CENTER_NOT_CONFIRMED,
}

CENTER_ANCHOR_IMAGE = "center_anchor.png"
CENTER_ANCHOR_META = "center_anchor.json"
CENTER_ANCHOR_ALGORITHM_VERSION = "center_anchor_v1"
CENTER_ANCHOR_DEFAULT_THRESHOLD = 0.80
SAFETY_TERMS_VERSION = 1
SAFETY_CONSENT_FILE = "safety_consent.json"

CenterEvent = Literal["none", "recheck", "confirmed", "lost"]


@dataclass
class CenterAnchor:
    name: str
    image_path: Path
    roi_size: list[int]
    node_id: str
    center_x: float | None
    center_y: float | None
    crop_ratio: float
    algorithm_version: str
    created_at: str
    updated_at: str

    def to_json(self, root: Path) -> dict:
        try:
            image_path = str(self.image_path.relative_to(root))
        except ValueError:
            image_path = str(self.image_path)
        return {
            "name": self.name,
            "image_path": image_path,
            "roi_size": self.roi_size,
            "node_id": self.node_id,
            "center_x": self.center_x,
            "center_y": self.center_y,
            "crop_ratio": self.crop_ratio,
            "algorithm_version": self.algorithm_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class CenterAnchorRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.db_dir = root / "db"
        self.image_path = self.db_dir / CENTER_ANCHOR_IMAGE
        self.meta_path = self.db_dir / CENTER_ANCHOR_META

    def load(self) -> CenterAnchor | None:
        if not self.image_path.exists() or not self.meta_path.exists():
            return None
        image = imread_unicode(self.image_path, cv2.IMREAD_UNCHANGED)
        if image is None or image.size == 0:
            return None
        try:
            raw = json.loads(self.meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        image_path = Path(raw.get("image_path") or self.image_path)
        if not image_path.is_absolute():
            image_path = self.root / image_path
        if image_path != self.image_path or not image_path.exists():
            image_path = self.image_path
        try:
            roi_size = [int(raw.get("roi_size", [image.shape[1], image.shape[0]])[0]), int(raw.get("roi_size", [image.shape[1], image.shape[0]])[1])]
        except (TypeError, ValueError, IndexError):
            roi_size = [int(image.shape[1]), int(image.shape[0])]
        return CenterAnchor(
            name=str(raw.get("name") or "Центр Bloodweb"),
            image_path=image_path,
            roi_size=roi_size,
            node_id=str(raw.get("node_id") or ""),
            center_x=float(raw["center_x"]) if raw.get("center_x") is not None else None,
            center_y=float(raw["center_y"]) if raw.get("center_y") is not None else None,
            crop_ratio=float(raw.get("crop_ratio") or NORMALIZATION_CROP_RATIO),
            algorithm_version=str(raw.get("algorithm_version") or CENTER_ANCHOR_ALGORITHM_VERSION),
            created_at=str(raw.get("created_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
        )

    def save(self, name: str, image, roi: NodeROI) -> CenterAnchor:
        self.db_dir.mkdir(parents=True, exist_ok=True)
        if image is None or image.size == 0:
            raise ValueError("Пустой снимок центра")
        ok = cv2.imwrite(str(self.image_path), image)
        if not ok:
            raise RuntimeError("Не удалось сохранить center_anchor.png")
        existing = self.load()
        now = datetime.now(timezone.utc).isoformat()
        anchor = CenterAnchor(
            name=name.strip() or "Центр Bloodweb",
            image_path=self.image_path,
            roi_size=[int(image.shape[1]), int(image.shape[0])],
            node_id=roi.node_id,
            center_x=float(roi.center_x),
            center_y=float(roi.center_y),
            crop_ratio=float(NORMALIZATION_CROP_RATIO),
            algorithm_version=CENTER_ANCHOR_ALGORITHM_VERSION,
            created_at=existing.created_at if existing and existing.created_at else now,
            updated_at=now,
        )
        self.meta_path.write_text(json.dumps(anchor.to_json(self.root), ensure_ascii=False, indent=2), encoding="utf-8")
        return anchor

    def save_point(self, image, center_x: float, center_y: float, roi_size: int) -> CenterAnchor:
        self.db_dir.mkdir(parents=True, exist_ok=True)
        if image is None or image.size == 0:
            raise ValueError("Пустой снимок центра")
        ok = cv2.imwrite(str(self.image_path), image)
        if not ok:
            raise RuntimeError("Не удалось сохранить center_anchor.png")
        existing = self.load()
        now = datetime.now(timezone.utc).isoformat()
        anchor = CenterAnchor(
            name="Центр Bloodweb",
            image_path=self.image_path,
            roi_size=[int(image.shape[1]), int(image.shape[0])],
            node_id="center_point",
            center_x=float(center_x),
            center_y=float(center_y),
            crop_ratio=float(NORMALIZATION_CROP_RATIO),
            algorithm_version=CENTER_ANCHOR_ALGORITHM_VERSION,
            created_at=existing.created_at if existing and existing.created_at else now,
            updated_at=now,
        )
        self.meta_path.write_text(json.dumps(anchor.to_json(self.root), ensure_ascii=False, indent=2), encoding="utf-8")
        return anchor


class CenterAnchorMatcher:
    def __init__(self, matcher: SnippetMatcher | None = None) -> None:
        self.matcher = matcher or SnippetMatcher()

    def score(self, anchor_image, roi_image, match_size: int, crop_ratio: float) -> float:
        anchor_variants = self.matcher.build_template_variants(anchor_image, match_size=match_size, crop_ratio=crop_ratio)
        anchor_descriptors = self.matcher.build_template_descriptors(anchor_variants)
        roi_variants = self.matcher.prepare_tone_variants(roi_image, target_size=match_size, crop_ratio=crop_ratio)
        best = 0.0
        for mode in TONE_VARIANT_MODES:
            if mode not in anchor_descriptors or mode not in roi_variants:
                continue
            roi_descriptor = self.matcher.make_descriptor(roi_variants[mode])
            best = max(best, self.matcher.mode_similarity(roi_descriptor, anchor_descriptors[mode]))
        return float(best)


class CenterConfirmationMachine:
    def __init__(self, configured: bool) -> None:
        self.state = CENTER_UNCONFIGURED if not configured else CENTER_NOT_CONFIRMED
        self.success_streak = 0
        self.clicks_allowed = False
        self.requires_manual_start = False

    def set_configured(self, configured: bool) -> None:
        self.state = CENTER_NOT_CONFIRMED if configured else CENTER_UNCONFIGURED
        self.success_streak = 0
        self.clicks_allowed = False
        self.requires_manual_start = False

    def regular_result(self, success: bool) -> CenterEvent:
        if self.state == CENTER_UNCONFIGURED:
            self.clicks_allowed = False
            self.success_streak = 0
            return "none"

        if self.state == CENTER_CONFIRMED:
            if success:
                self.success_streak = 2
                self.clicks_allowed = True
                return "none"
            self.state = CENTER_RECHECKING
            self.success_streak = 0
            self.clicks_allowed = False
            return "recheck"

        if success:
            self.success_streak += 1
            if self.success_streak >= 2:
                self.state = CENTER_CONFIRMED
                self.clicks_allowed = True
                return "confirmed"
        else:
            self.success_streak = 0
            self.clicks_allowed = False
            if self.state != CENTER_RECHECKING:
                self.state = CENTER_NOT_CONFIRMED
        return "none"

    def recheck_results(self, successes: list[bool]) -> CenterEvent:
        if any(successes):
            self.state = CENTER_CONFIRMED
            self.success_streak = 2
            self.clicks_allowed = True
            return "confirmed"
        self.state = CENTER_NOT_CONFIRMED
        self.success_streak = 0
        self.clicks_allowed = False
        self.requires_manual_start = False
        return "lost"

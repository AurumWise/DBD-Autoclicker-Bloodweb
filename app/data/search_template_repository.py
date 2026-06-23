from __future__ import annotations

import json
from pathlib import Path

from app.vision.image_io import imread_unicode
from app.vision.snippet_matcher import NORMALIZATION_CROP_RATIO, VARIANT_ALGORITHM_VERSION


DEFAULT_DATA = {
    "schema_version": 2,
    "survivor_templates": [
        {
            "name": "default_survivor",
            "items": [],
        }
    ],
    "killer_templates": [
        {
            "name": "default_killer",
            "killer_id": None,
            "items": [],
        }
    ],
    "priority_items": [],
}


class SearchTemplateRepository:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.path = root_dir / "db" / "search_templates.json"
        self.image_dir = root_dir / "db" / "user_templates"
        self.image_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        if not self.path.exists():
            return json.loads(json.dumps(DEFAULT_DATA))
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return json.loads(json.dumps(DEFAULT_DATA))
        return self.normalize(data)

    def save(self, payload: dict) -> None:
        normalized = self.normalize(payload)
        self.make_paths_portable(normalized)
        self.path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")

    def normalize(self, data: dict) -> dict:
        result = json.loads(json.dumps(DEFAULT_DATA))

        survivor_templates = []
        for item in data.get("survivor_templates", []):
            survivor_templates.append(
                {
                    "name": item.get("name", "survivor_template"),
                    "items": self.normalize_items(item.get("items", item.get("entries", []))),
                }
            )
        if survivor_templates:
            result["survivor_templates"] = survivor_templates

        killer_templates = []
        for item in data.get("killer_templates", []):
            killer_templates.append(
                {
                    "name": item.get("name", "killer_template"),
                    "killer_id": item.get("killer_id"),
                    "items": self.normalize_items(item.get("items", item.get("entries", []))),
                }
            )
        if killer_templates:
            result["killer_templates"] = killer_templates

        result["priority_items"] = self.normalize_items(data.get("priority_items", data.get("priority_offerings", [])))
        return result

    def normalize_items(self, items: list) -> list[dict]:
        normalized: list[dict] = []
        for item in items:
            if isinstance(item, dict):
                image_path = item.get("image_path")
                resolved_path = self.resolve_image_path(image_path)
                if resolved_path and resolved_path.exists():
                    normalized_item = {
                        "id": item.get("id") or resolved_path.stem,
                        "label": item.get("label") or item.get("name") or item.get("id") or "template",
                        "image_path": str(resolved_path),
                    }
                    for key in ("image_width", "image_height", "match_size", "capture_roi_size", "crop_ratio", "variant_algorithm"):
                        if key in item:
                            normalized_item[key] = item[key]
                    self.enrich_item_metadata_from_png(normalized_item)
                    normalized.append(normalized_item)
            # legacy string entries are dropped on purpose: the new mode is user-captured snippets only.
        return normalized

    def resolve_image_path(self, image_path: str | None) -> Path | None:
        if not image_path:
            return None
        path = Path(image_path)
        if path.is_absolute():
            return path
        return self.root_dir / path

    def make_paths_portable(self, payload: dict) -> None:
        for item in self.iter_items(payload):
            image_path = item.get("image_path")
            resolved_path = self.resolve_image_path(image_path)
            if not resolved_path:
                continue
            try:
                item["image_path"] = str(resolved_path.relative_to(self.root_dir))
            except ValueError:
                item["image_path"] = str(resolved_path)

    @staticmethod
    def iter_items(payload: dict):
        for item in payload.get("priority_items", []):
            yield item
        for template in payload.get("survivor_templates", []):
            yield from template.get("items", [])
        for template in payload.get("killer_templates", []):
            yield from template.get("items", [])

    def enrich_item_metadata_from_png(self, item: dict) -> None:
        image_path = item.get("image_path")
        if not image_path:
            return
        image = imread_unicode(self.resolve_image_path(image_path), -1)
        if image is None:
            return
        height, width = image.shape[:2]
        defaults = {
            "image_width": int(width),
            "image_height": int(height),
            "match_size": max(32, int(min(width, height))),
            "crop_ratio": float(NORMALIZATION_CROP_RATIO),
        }
        for key, value in defaults.items():
            item.setdefault(key, value)
        item["variant_algorithm"] = VARIANT_ALGORITHM_VERSION

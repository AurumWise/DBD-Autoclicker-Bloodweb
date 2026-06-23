from __future__ import annotations

import json
import math
from pathlib import Path

from app.models import GridTemplate, NodeROI


RING_ANGLES = {
    1: [-90.0, -30.0, 30.0, 90.0, 150.0, 210.0],
    2: [-75.0, -45.0, -15.0, 15.0, 45.0, 75.0, 105.0, 135.0, 165.0, 195.0, 225.0, 255.0],
    3: [-90.0, -60.0, -30.0, 0.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0, 210.0, 240.0],
}

RING_SPECS = {ring: {"count": len(angles), "angles_deg": angles} for ring, angles in RING_ANGLES.items()}


class GridTemplateRepository:
    def __init__(self, root_dir: Path) -> None:
        self.path = root_dir / "db" / "grid_templates.json"

    def list_templates(self) -> list[GridTemplate]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        result: list[GridTemplate] = []
        for item in raw.get("templates", []):
            result.append(
                GridTemplate(
                    name=item["name"],
                    screenshot=item.get("screenshot", ""),
                    image_size=item.get("image_size"),
                    center_x=float(item["center_x"]),
                    center_y=float(item["center_y"]),
                    ring1_radius=float(item["ring1_radius"]),
                    ring2_radius=float(item["ring2_radius"]),
                    ring3_radius=float(item["ring3_radius"]),
                    rotation_deg=float(item.get("rotation_deg", 0.0)),
                    roi_size=float(item["roi_size"]),
                )
            )
        return result

    def get_template(self, name: str) -> GridTemplate | None:
        for template in self.list_templates():
            if template.name == name:
                return template
        return None


def build_rois(template: GridTemplate, image_width: int, image_height: int) -> list[NodeROI]:
    rois: list[NodeROI] = []
    half = template.roi_size / 2.0
    for ring, spec in RING_SPECS.items():
        radius = getattr(template, f"ring{ring}_radius")
        for index, angle_deg in enumerate(spec["angles_deg"]):
            x, y = transform_point(template, radius, angle_deg)
            x1 = max(0, int(round(x - half)))
            y1 = max(0, int(round(y - half)))
            x2 = min(image_width, int(round(x + half)))
            y2 = min(image_height, int(round(y + half)))
            if x2 - x1 < 10 or y2 - y1 < 10:
                continue
            rois.append(
                NodeROI(
                    node_id=f"ring{ring}_{index + 1:02d}",
                    ring=ring,
                    index=index,
                    angle_deg=angle_deg,
                    center_x=x,
                    center_y=y,
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    distance_from_center=radius,
                )
            )
    return rois


def transform_point(template: GridTemplate, radius: float, angle_deg: float) -> tuple[float, float]:
    angle = math.radians(angle_deg + template.rotation_deg)
    return (
        template.center_x + math.cos(angle) * radius,
        template.center_y + math.sin(angle) * radius,
    )

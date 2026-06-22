from __future__ import annotations

import json
import logging
from pathlib import Path

import cv2
import numpy as np

from app.vision.image_io import imread_unicode


PERCENTILE_LOW = 3.0
PERCENTILE_HIGH = 99.0
CLAHE_CLIP_LIMIT = 1.6
CLAHE_TILE_GRID_SIZE = (4, 4)
LIGHT_GAMMA = 0.75
DARK_GAMMA = 1.18
LIGHT_OUTPUT_LOW = 12
LIGHT_OUTPUT_HIGH = 250
DARK_OUTPUT_LOW = 12
DARK_OUTPUT_HIGH = 175
NORMALIZATION_CROP_RATIO = 0.75
NODE_CONTENT_SIZE = 96
VARIANT_ALGORITHM_VERSION = "tone_variants_v1"
TONE_VARIANT_MODES = ("light", "dark")
NORMALIZATION_CONFIG = {
    "crop_ratio": NORMALIZATION_CROP_RATIO,
    "resize_size": NODE_CONTENT_SIZE,
    "percentile_low": PERCENTILE_LOW,
    "percentile_high": PERCENTILE_HIGH,
    "clahe_clip_limit": CLAHE_CLIP_LIMIT,
    "clahe_tile_grid": CLAHE_TILE_GRID_SIZE,
    "gamma_light": LIGHT_GAMMA,
    "gamma_dark": DARK_GAMMA,
}
TEMPLATE_SCALES = (0.94, 1.00, 1.06)
SHIFT_OFFSETS = (-4, 0, 4)
VARIANT_DIR_NAME = ".variants_size_v2"
VARIANT_FILE_SUFFIX = ".npy"
VARIANT_MANIFEST_NAME = "manifest.json"
# Detail verification is a conservative reject-only gate for ambiguous primary matches.
DETAIL_SILHOUETTE_MIN_SCORE = 0.42
DETAIL_EDGE_MIN_SCORE = 0.16
DETAIL_SHIFT_RADIUS_PIXELS = 3
DETAIL_MIN_FOREGROUND_RATIO = 0.025
DETAIL_MAX_FOREGROUND_RATIO = 0.65


logger = logging.getLogger(__name__)


class SnippetMatcher:
    def __init__(self) -> None:
        self._cache: dict[str, dict[str, list[dict]]] = {}
        self._mask_cache: dict[int, np.ndarray] = {}
        self._clahe = cv2.createCLAHE(
            clipLimit=CLAHE_CLIP_LIMIT,
            tileGridSize=CLAHE_TILE_GRID_SIZE,
        )

    def prepare_items(self, items: list[dict]) -> list[dict]:
        prepared = []
        for item in items:
            templates = self.load_template_variants(item)
            if not self.template_variant_set_complete(templates):
                continue
            prepared.append({"item": item, "templates": templates, "target_size": self.template_variant_size(templates)})
        return prepared

    def match_roi(self, crop: np.ndarray, items: list[dict], top_n: int = 5) -> list[dict]:
        return self.match_roi_prepared(crop, self.prepare_items(items), top_n)

    def match_roi_prepared(self, crop: np.ndarray, prepared_items: list[dict], top_n: int = 5, roi_id: str | None = None) -> list[dict]:
        roi_cache: dict[int, dict[str, dict]] = {}
        results: list[dict] = []
        for prepared in prepared_items:
            item = prepared["item"]
            templates = prepared["templates"]
            target_size = int(prepared["target_size"])
            if not self.template_variant_set_complete(templates):
                continue
            if target_size not in roi_cache:
                roi_variants = self.prepare_tone_variants(crop, target_size)
                roi_cache[target_size] = {mode: self.make_descriptor(roi_variants[mode]) for mode in TONE_VARIANT_MODES}
            roi_variants = roi_cache[target_size]
            light_score, light_template_image, light_roi_image = self.mode_similarity_with_pair(roi_variants["light"], templates["light"])
            dark_score, dark_template_image, dark_roi_image = self.mode_similarity_with_pair(roi_variants["dark"], templates["dark"])
            best_mode = "light" if light_score >= dark_score else "dark"
            best_score = max(light_score, dark_score)
            if best_mode == "light":
                detail_pair = {"template": light_template_image, "roi": light_roi_image}
            else:
                detail_pair = {"template": dark_template_image, "roi": dark_roi_image}
            logger.debug(
                "template=%s roi=%s light=%.4f dark=%.4f best=%.4f mode=%s",
                item.get("label") or item.get("id") or item.get("image_path"),
                roi_id or "-",
                light_score,
                dark_score,
                best_score,
                best_mode,
            )
            results.append(
                {
                    "id": item["id"],
                    "label": item["label"],
                    "image_path": item["image_path"],
                    "score": best_score,
                    "best_score": best_score,
                    "best_mode": best_mode,
                    "light_score": light_score,
                    "dark_score": dark_score,
                    "_detail_pair": detail_pair,
                }
            )
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:top_n]

    def load_template_variants(self, item_or_image_path: dict | str | Path) -> dict[str, list[dict]]:
        item = item_or_image_path if isinstance(item_or_image_path, dict) else {"image_path": str(item_or_image_path)}
        image_path = item.get("image_path")
        if not image_path:
            return {}
        path = Path(image_path)
        if not path.exists():
            return {}
        match_size = self.expected_match_size(item, path)
        if match_size <= 0:
            return {}
        crop_ratio = self.expected_crop_ratio(item)
        cache_key = self.cache_key(path, match_size, crop_ratio)
        if cache_key in self._cache:
            return self._cache[cache_key]

        variants = self.load_precomputed_template_variants(path, match_size, crop_ratio)
        if not variants:
            variants = self.ensure_template_variant_files(path, match_size=match_size, crop_ratio=crop_ratio)
        self._cache[cache_key] = variants
        return variants

    def ensure_template_variant_files(
        self,
        image_path: Path | str,
        match_size: int | None = None,
        crop_ratio: float | None = None,
        persist: bool | None = None,
    ) -> dict[str, list[dict]]:
        image_path = Path(image_path)
        image = imread_unicode(image_path, cv2.IMREAD_UNCHANGED)
        if image is None:
            return {}
        match_size = int(match_size or self.default_match_size_for_image(image))
        crop_ratio = float(crop_ratio if crop_ratio is not None else self.normalization_crop_ratio())
        variants = self.build_template_variants(image, match_size=match_size, crop_ratio=crop_ratio)
        should_persist = persist if persist is not None else self.should_persist_variant_files(image_path)
        if should_persist:
            self.save_precomputed_template_variants(image_path, variants, match_size, crop_ratio)
        descriptors = self.build_template_descriptors(variants)
        self._cache[self.cache_key(image_path, match_size, crop_ratio)] = descriptors
        return descriptors

    def load_precomputed_template_variants(self, image_path: Path, match_size: int, crop_ratio: float) -> dict[str, list[dict]]:
        variants = self.load_precomputed_tone_variant_arrays(image_path, match_size, crop_ratio)
        if not variants:
            return {}
        return self.build_template_descriptors(variants)

    def load_precomputed_tone_variant_arrays(self, image_path: Path, match_size: int, crop_ratio: float) -> dict[str, np.ndarray]:
        variant_dir = self.variant_dir_for(image_path)
        if not variant_dir.exists():
            return {}
        manifest_path = variant_dir / VARIANT_MANIFEST_NAME
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if manifest.get("algorithm") != VARIANT_ALGORITHM_VERSION:
            return {}
        try:
            manifest_match_size = int(manifest.get("match_size", 0))
            manifest_crop_ratio = float(manifest.get("crop_ratio", -1.0))
        except (TypeError, ValueError):
            return {}
        if manifest_match_size != int(match_size):
            return {}
        if abs(manifest_crop_ratio - float(crop_ratio)) > 1e-6:
            return {}

        variants: dict[str, np.ndarray] = {}
        expected_shape = (int(match_size), int(match_size))
        for mode in TONE_VARIANT_MODES:
            path = variant_dir / f"{mode}{VARIANT_FILE_SUFFIX}"
            try:
                variant = np.load(path, allow_pickle=False)
            except (OSError, ValueError):
                return {}
            if variant.dtype != np.uint8 or variant.shape != expected_shape:
                return {}
            variants[mode] = variant
        return variants

    def save_precomputed_template_variants(
        self,
        image_path: Path,
        variants: dict[str, np.ndarray],
        match_size: int,
        crop_ratio: float,
    ) -> None:
        variant_dir = self.variant_dir_for(image_path)
        variant_dir.mkdir(parents=True, exist_ok=True)
        for old_file in variant_dir.glob(f"*{VARIANT_FILE_SUFFIX}"):
            old_file.unlink()
        for mode in TONE_VARIANT_MODES:
            np.save(variant_dir / f"{mode}{VARIANT_FILE_SUFFIX}", variants[mode])
        manifest = {
            "algorithm": VARIANT_ALGORITHM_VERSION,
            "match_size": int(match_size),
            "crop_ratio": float(crop_ratio),
            "modes": list(TONE_VARIANT_MODES),
        }
        (variant_dir / VARIANT_MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def build_template_variants(
        self,
        image: np.ndarray,
        match_size: int | None = None,
        crop_ratio: float | None = None,
    ) -> dict[str, np.ndarray]:
        return self.prepare_tone_variants(
            image,
            int(match_size or self.default_match_size_for_image(image)),
            float(crop_ratio if crop_ratio is not None else self.normalization_crop_ratio()),
        )

    def build_template_descriptors(self, variants: dict[str, np.ndarray]) -> dict[str, list[dict]]:
        return {
            mode: [self.make_descriptor(self.scale_to_canvas(variants[mode], scale), include_shifts=True) for scale in TEMPLATE_SCALES]
            for mode in TONE_VARIANT_MODES
            if mode in variants
        }

    @staticmethod
    def variant_dir_for(image_path: Path) -> Path:
        return image_path.parent / VARIANT_DIR_NAME / image_path.stem

    @staticmethod
    def normalization_crop_ratio() -> float:
        return NORMALIZATION_CROP_RATIO

    @staticmethod
    def variant_algorithm_version() -> str:
        return VARIANT_ALGORITHM_VERSION

    def prepare_image(self, image: np.ndarray, target_size: int | None = None) -> np.ndarray:
        return self.prepare_tone_variants(image, target_size)["light"]

    def prepare_image_variants(self, image: np.ndarray, target_size: int | None = None) -> list[np.ndarray]:
        variants = self.prepare_tone_variants(image, target_size)
        return [variants[mode] for mode in TONE_VARIANT_MODES]

    def prepare_tone_variants(
        self,
        image: np.ndarray,
        target_size: int | None = None,
        crop_ratio: float | None = None,
    ) -> dict[str, np.ndarray]:
        cropped = self.center_crop(image, float(crop_ratio if crop_ratio is not None else self.normalization_crop_ratio()))
        gray = self.to_grayscale(cropped)
        size = int(target_size or self.default_match_size_for_cropped_image(gray))
        resized = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
        base = self.normalize_grayscale(resized)
        return self.build_tone_variants_from_base(base)

    def default_match_size_for_image(self, image: np.ndarray) -> int:
        height, width = image.shape[:2]
        return max(32, int(min(width, height)))

    @staticmethod
    def default_match_size_for_cropped_image(image: np.ndarray) -> int:
        height, width = image.shape[:2]
        return max(32, int(min(width, height)))

    def normalized_color_variants(self, image: np.ndarray) -> list[np.ndarray]:
        base = self.normalize_grayscale(self.to_grayscale(image))
        variants = self.build_tone_variants_from_base(base)
        return [variants[mode] for mode in TONE_VARIANT_MODES]

    def make_descriptor(self, image: np.ndarray, include_shifts: bool = False) -> dict:
        gray = self.to_grayscale(image)
        mask = self.circle_mask_cached(gray.shape[0], 0.44)
        hist = cv2.calcHist([gray], [0], mask, [32], [0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
        descriptor = {"image": gray, "l": gray, "hist": hist.astype(np.float32)}
        if include_shifts:
            descriptor["shifts"] = [
                (self.shift_image(gray, dx, dy), self.shift_channel(gray, dx, dy))
                for dx in SHIFT_OFFSETS
                for dy in SHIFT_OFFSETS
            ]
        return descriptor

    def roi_has_node_like_content(self, crop: np.ndarray) -> bool:
        size = NODE_CONTENT_SIZE
        gray = self.to_grayscale(crop)
        gray = self.center_crop(gray, self.normalization_crop_ratio())
        l_channel = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
        inner_mask = self.circle_mask(size, radius_scale=0.42)
        ring_mask = self.ring_mask(size, inner_scale=0.34, outer_scale=0.50)
        inner_pixels = l_channel[inner_mask > 0]
        if inner_pixels.size == 0:
            return False
        edges = cv2.Canny(l_channel, 50, 150)
        ring_edges = edges[ring_mask > 0]
        inner_std = float(np.std(inner_pixels))
        ring_edge_ratio = float(np.count_nonzero(ring_edges)) / float(ring_edges.size if ring_edges.size else 1)
        return not (inner_std < 14.0 and ring_edge_ratio < 0.04)

    @staticmethod
    def template_variant_set_complete(templates: dict[str, list[dict]]) -> bool:
        return all(mode in templates and bool(templates[mode]) for mode in TONE_VARIANT_MODES)

    @staticmethod
    def template_variant_size(templates: dict[str, list[dict]]) -> int:
        for mode in TONE_VARIANT_MODES:
            if mode in templates and templates[mode]:
                return int(templates[mode][0]["image"].shape[0])
        return 0

    def mode_similarity(self, roi: dict, templates: list[dict]) -> float:
        score, _template_image, _roi_image = self.mode_similarity_with_pair(roi, templates)
        return score

    def mode_similarity_with_pair(self, roi: dict, templates: list[dict]) -> tuple[float, np.ndarray | None, np.ndarray | None]:
        best_score = 0.0
        best_template_image = None
        for template in templates:
            score, template_image = self.template_similarity_with_pair(roi, template)
            if score > best_score:
                best_score = score
                best_template_image = template_image
        return best_score, best_template_image, roi.get("image")

    def template_similarity(self, roi: dict[str, np.ndarray], template: dict[str, np.ndarray]) -> float:
        score, _template_image = self.template_similarity_with_pair(roi, template)
        return score

    def template_similarity_with_pair(self, roi: dict[str, np.ndarray], template: dict[str, np.ndarray]) -> tuple[float, np.ndarray | None]:
        best = 0.0
        best_template_image = None
        hist_corr = cv2.compareHist(roi["hist"], template["hist"], cv2.HISTCMP_CORREL)
        if not np.isfinite(hist_corr):
            hist_corr = -1.0
        hist_score = max(0.0, min(1.0, (float(hist_corr) + 1.0) / 2.0))
        for shifted_image, shifted_l in template.get("shifts", [(template["image"], template["l"])]):
            score = self.single_template_similarity(roi, shifted_image, shifted_l, hist_score)
            if score > best:
                best = score
                best_template_image = shifted_image
        return best, best_template_image

    def single_template_similarity(self, roi: dict[str, np.ndarray], template_image: np.ndarray, template_l: np.ndarray, hist_score: float) -> float:
        size = int(roi["image"].shape[0])
        mask = self.circle_mask_cached(size, 0.44)
        roi_f = roi["image"].astype(np.float32)
        template_f = template_image.astype(np.float32)

        color_diff = cv2.absdiff(roi_f, template_f)
        masked_diff = color_diff[mask > 0]
        mean_diff = float(np.mean(masked_diff)) if masked_diff.size else 255.0
        diff_score = max(0.0, 1.0 - (mean_diff / 85.0))

        corr = float(cv2.matchTemplate(roi["l"], template_l, cv2.TM_CCOEFF_NORMED)[0][0])
        if not np.isfinite(corr):
            corr = -1.0
        corr_score = max(0.0, min(1.0, (corr + 1.0) / 2.0))

        return float((diff_score * 0.45) + (corr_score * 0.35) + (hist_score * 0.20))

    @staticmethod
    def should_run_detail_verification(primary_score: float, minimum: float, maximum: float) -> bool:
        return float(minimum) <= float(primary_score) <= float(maximum)

    def verify_candidate_detail(self, candidate: dict, roi_id: str | None = None) -> dict:
        pair = candidate.get("_detail_pair") or {}
        template_image = pair.get("template")
        roi_image = pair.get("roi")
        template_name = candidate.get("label") or candidate.get("id") or candidate.get("image_path")
        primary = float(candidate.get("score", 0.0))
        mode = candidate.get("best_mode", "-")

        result = self.detail_verify_images(template_image, roi_image)
        logger.debug(
            "detail_verify: template=%s roi=%s mode=%s primary=%.4f silhouette=%.4f edges=%.4f result=%s reason=%s",
            template_name,
            roi_id or "-",
            mode,
            primary,
            result["silhouette_score"],
            result["edge_score"],
            "PASS" if result["detail_passed"] else "REJECT",
            result.get("reason", ""),
        )
        return result

    def detail_verify_images(self, template_image: np.ndarray | None, roi_image: np.ndarray | None) -> dict:
        if template_image is None or roi_image is None:
            return self.detail_result(False, 0.0, 0.0, "missing winning pair")
        try:
            template = self.to_grayscale(template_image)
            roi = self.to_grayscale(roi_image)
        except (cv2.error, ValueError) as exc:
            return self.detail_result(False, 0.0, 0.0, f"invalid image: {exc}")
        if template.size == 0 or roi.size == 0:
            return self.detail_result(False, 0.0, 0.0, "empty image")
        if template.shape != roi.shape:
            return self.detail_result(False, 0.0, 0.0, "shape mismatch")

        template_mask = self.foreground_mask(template)
        roi_mask = self.foreground_mask(roi)
        if template_mask is None or roi_mask is None:
            return self.detail_result(False, 0.0, 0.0, "foreground mask failed")

        silhouette_score = self.best_shifted_mask_score(template_mask, roi_mask)
        template_edges = self.edge_map(template, template_mask)
        roi_edges = self.edge_map(roi, roi_mask)
        edge_score = self.best_shifted_mask_score(template_edges, roi_edges)
        passed = silhouette_score >= DETAIL_SILHOUETTE_MIN_SCORE and edge_score >= DETAIL_EDGE_MIN_SCORE
        reason = "ok" if passed else "detail thresholds not met"
        return self.detail_result(passed, silhouette_score, edge_score, reason)

    @staticmethod
    def detail_result(passed: bool, silhouette_score: float, edge_score: float, reason: str) -> dict:
        return {
            "detail_passed": bool(passed),
            "silhouette_score": float(silhouette_score),
            "edge_score": float(edge_score),
            "reason": reason,
        }

    def foreground_mask(self, gray: np.ndarray) -> np.ndarray | None:
        if gray.dtype != np.uint8 or gray.ndim != 2:
            return None
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        _threshold, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        circle = self.circle_mask_cached(gray.shape[0], 0.43)
        mask = cv2.bitwise_and(mask, circle)
        kernel = np.ones((3, 3), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = self.keep_significant_components(mask)
        area_ratio = float(np.count_nonzero(mask)) / float(np.count_nonzero(circle) or 1)
        if area_ratio < DETAIL_MIN_FOREGROUND_RATIO or area_ratio > DETAIL_MAX_FOREGROUND_RATIO:
            return None
        return mask

    @staticmethod
    def keep_significant_components(mask: np.ndarray) -> np.ndarray:
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if count <= 1:
            return mask
        areas = stats[1:, cv2.CC_STAT_AREA]
        if areas.size == 0:
            return mask
        max_area = int(np.max(areas))
        min_area = max(8, int(max_area * 0.08))
        cleaned = np.zeros_like(mask)
        for label in range(1, count):
            if int(stats[label, cv2.CC_STAT_AREA]) >= min_area:
                cleaned[labels == label] = 255
        return cleaned

    def edge_map(self, gray: np.ndarray, foreground_mask: np.ndarray) -> np.ndarray:
        edges = cv2.Canny(gray, 50, 150)
        kernel = np.ones((3, 3), dtype=np.uint8)
        foreground = cv2.dilate(foreground_mask, kernel, iterations=1)
        edges = cv2.bitwise_and(edges, foreground)
        return cv2.dilate(edges, kernel, iterations=1)

    def best_shifted_mask_score(self, template_mask: np.ndarray, roi_mask: np.ndarray) -> float:
        if template_mask.shape != roi_mask.shape:
            return 0.0
        best = 0.0
        for dx in range(-DETAIL_SHIFT_RADIUS_PIXELS, DETAIL_SHIFT_RADIUS_PIXELS + 1):
            for dy in range(-DETAIL_SHIFT_RADIUS_PIXELS, DETAIL_SHIFT_RADIUS_PIXELS + 1):
                shifted = self.shift_channel(template_mask, dx, dy)
                best = max(best, self.dice_score(shifted, roi_mask))
        return best

    @staticmethod
    def dice_score(first: np.ndarray, second: np.ndarray) -> float:
        first_bool = first > 0
        second_bool = second > 0
        total = int(np.count_nonzero(first_bool) + np.count_nonzero(second_bool))
        if total == 0:
            return 0.0
        intersection = int(np.count_nonzero(first_bool & second_bool))
        return float((2.0 * intersection) / total)

    @staticmethod
    def expected_crop_ratio(item: dict) -> float:
        try:
            value = float(item.get("crop_ratio", NORMALIZATION_CROP_RATIO))
        except (TypeError, ValueError):
            value = NORMALIZATION_CROP_RATIO
        if not 0.0 < value <= 1.0:
            return NORMALIZATION_CROP_RATIO
        return value

    def expected_match_size(self, item: dict, image_path: Path) -> int:
        try:
            value = int(item.get("match_size", 0))
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
        image = imread_unicode(image_path, cv2.IMREAD_UNCHANGED)
        if image is None:
            return 0
        return self.default_match_size_for_image(image)

    @staticmethod
    def should_persist_variant_files(image_path: Path) -> bool:
        return image_path.parent.name == "user_templates"

    @staticmethod
    def cache_key(image_path: Path, match_size: int, crop_ratio: float) -> str:
        return f"{image_path.resolve()}|{int(match_size)}|{float(crop_ratio):.6f}|{VARIANT_ALGORITHM_VERSION}"

    def normalize_grayscale(self, gray: np.ndarray) -> np.ndarray:
        stretched = self.percentile_stretch(gray)
        return self._clahe.apply(stretched)

    def build_tone_variants_from_base(self, base: np.ndarray) -> dict[str, np.ndarray]:
        light = self.output_range_map(self.apply_gamma(base, LIGHT_GAMMA), LIGHT_OUTPUT_LOW, LIGHT_OUTPUT_HIGH)
        dark = self.output_range_map(self.apply_gamma(base, DARK_GAMMA), DARK_OUTPUT_LOW, DARK_OUTPUT_HIGH)
        return {
            "light": cv2.GaussianBlur(light, (3, 3), 0),
            "dark": cv2.GaussianBlur(dark, (3, 3), 0),
        }

    @staticmethod
    def to_grayscale(image: np.ndarray) -> np.ndarray:
        if image.ndim == 2:
            gray = image
        elif image.ndim == 3 and image.shape[2] == 1:
            gray = image[:, :, 0]
        elif image.ndim == 3 and image.shape[2] == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        elif image.ndim == 3 and image.shape[2] == 4:
            gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        else:
            raise ValueError(f"Unsupported image shape for matcher: {image.shape}")
        if gray.dtype == np.uint8:
            return gray
        return np.clip(gray, 0, 255).astype(np.uint8)

    @staticmethod
    def scale_to_canvas(image: np.ndarray, scale: float) -> np.ndarray:
        height, width = image.shape[:2]
        scaled_w = max(1, int(round(width * scale)))
        scaled_h = max(1, int(round(height * scale)))
        resized = cv2.resize(image, (scaled_w, scaled_h), interpolation=cv2.INTER_AREA)
        canvas = np.zeros_like(image)
        src_x1 = max(0, (scaled_w - width) // 2)
        src_y1 = max(0, (scaled_h - height) // 2)
        dst_x1 = max(0, (width - scaled_w) // 2)
        dst_y1 = max(0, (height - scaled_h) // 2)
        copy_w = min(width - dst_x1, scaled_w - src_x1)
        copy_h = min(height - dst_y1, scaled_h - src_y1)
        canvas[dst_y1 : dst_y1 + copy_h, dst_x1 : dst_x1 + copy_w] = resized[src_y1 : src_y1 + copy_h, src_x1 : src_x1 + copy_w]
        return canvas

    @staticmethod
    def center_crop(image: np.ndarray, ratio: float) -> np.ndarray:
        if ratio >= 1.0:
            return image
        height, width = image.shape[:2]
        crop_w = max(1, int(round(width * ratio)))
        crop_h = max(1, int(round(height * ratio)))
        x1 = max(0, (width - crop_w) // 2)
        y1 = max(0, (height - crop_h) // 2)
        return image[y1 : y1 + crop_h, x1 : x1 + crop_w]

    @staticmethod
    def percentile_stretch(channel: np.ndarray) -> np.ndarray:
        lo, hi = np.percentile(channel, (PERCENTILE_LOW, PERCENTILE_HIGH))
        if hi <= lo:
            return channel.copy()
        stretched = (channel.astype(np.float32) - lo) * (255.0 / (hi - lo))
        return np.clip(stretched, 0, 255).astype(np.uint8)

    @staticmethod
    def apply_gamma(channel: np.ndarray, gamma: float) -> np.ndarray:
        normalized = channel.astype(np.float32) / 255.0
        corrected = np.power(normalized, gamma) * 255.0
        return np.clip(corrected, 0, 255).astype(np.uint8)

    @staticmethod
    def output_range_map(channel: np.ndarray, output_low: int, output_high: int) -> np.ndarray:
        scaled = channel.astype(np.float32) * (float(output_high - output_low) / 255.0) + float(output_low)
        return np.clip(scaled, 0, 255).astype(np.uint8)

    @staticmethod
    def shift_image(image: np.ndarray, dx: int, dy: int) -> np.ndarray:
        height, width = image.shape[:2]
        shifted = np.zeros_like(image)
        src_x1 = max(0, -dx)
        src_y1 = max(0, -dy)
        dst_x1 = max(0, dx)
        dst_y1 = max(0, dy)
        copy_w = min(width - src_x1, width - dst_x1)
        copy_h = min(height - src_y1, height - dst_y1)
        if copy_w <= 0 or copy_h <= 0:
            return shifted
        shifted[dst_y1 : dst_y1 + copy_h, dst_x1 : dst_x1 + copy_w] = image[src_y1 : src_y1 + copy_h, src_x1 : src_x1 + copy_w]
        return shifted

    @staticmethod
    def shift_channel(channel: np.ndarray, dx: int, dy: int) -> np.ndarray:
        height, width = channel.shape[:2]
        shifted = np.zeros_like(channel)
        src_x1 = max(0, -dx)
        src_y1 = max(0, -dy)
        dst_x1 = max(0, dx)
        dst_y1 = max(0, dy)
        copy_w = min(width - src_x1, width - dst_x1)
        copy_h = min(height - src_y1, height - dst_y1)
        if copy_w <= 0 or copy_h <= 0:
            return shifted
        shifted[dst_y1 : dst_y1 + copy_h, dst_x1 : dst_x1 + copy_w] = channel[src_y1 : src_y1 + copy_h, src_x1 : src_x1 + copy_w]
        return shifted

    def circle_mask_cached(self, size: int, radius_scale: float = 0.44) -> np.ndarray:
        key = int(size * 1000 + radius_scale * 100)
        if key not in self._mask_cache:
            self._mask_cache[key] = self.circle_mask(size, radius_scale)
        return self._mask_cache[key]

    @staticmethod
    def circle_mask(size: int, radius_scale: float = 0.44) -> np.ndarray:
        mask = np.zeros((size, size), dtype=np.uint8)
        cv2.circle(mask, (size // 2, size // 2), int(size * radius_scale), 255, thickness=-1)
        return mask

    @staticmethod
    def ring_mask(size: int, inner_scale: float, outer_scale: float) -> np.ndarray:
        outer = SnippetMatcher.circle_mask(size, radius_scale=outer_scale)
        inner = SnippetMatcher.circle_mask(size, radius_scale=inner_scale)
        return cv2.subtract(outer, inner)

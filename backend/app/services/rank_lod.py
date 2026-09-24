"""Zoom-based rank LOD — keep in sync with ``frontend/src/rankLod.ts``."""

from __future__ import annotations

LOD_START_ZOOM = 2
LOD_STEP_COUNT = 6
LOD_ALL_LEVEL = LOD_STEP_COUNT
DEFAULT_LOD_LEVEL = 3
LOD_CURVE_STEP_COUNT = LOD_STEP_COUNT - 1


def clamp_lod_level(level: int) -> int:
    return min(LOD_STEP_COUNT, max(1, int(round(level))))


def is_show_all_lod(level: int) -> bool:
    return clamp_lod_level(level) == LOD_ALL_LEVEL


def aggressiveness_for_lod_level(level: int) -> int:
    level = clamp_lod_level(level)
    if is_show_all_lod(level):
        return 100
    # Steps 1..5 → 0, 25, 50, 75, 100
    i = level - 1
    return round(i / (LOD_CURVE_STEP_COUNT - 1) * 100)


def lod_params_for_aggressiveness(aggressiveness: float) -> tuple[int, float]:
    a = min(100.0, max(0.0, float(aggressiveness)))
    if a <= 50:
        t = a / 50.0
        base = round(250 + t * (1_000 - 250))
        growth = 1.5 + t * (4 - 1.5)
        return base, growth
    t = (a - 50) / 50.0
    base = round(1_000 + t * (4_000 - 1_000))
    growth = 4 + t * (8 - 4)
    return base, growth


def rank_max_for_zoom(
    zoom: float,
    dataset_rank_max: int,
    lod_level: int = DEFAULT_LOD_LEVEL,
) -> int:
    dataset_rank_max = max(1, int(dataset_rank_max))
    if is_show_all_lod(lod_level):
        return dataset_rank_max
    aggressiveness = aggressiveness_for_lod_level(lod_level)
    base, growth = lod_params_for_aggressiveness(aggressiveness)
    z = int(zoom)
    exponent = max(0, z - LOD_START_ZOOM)
    from_zoom = round(base * (growth**exponent))
    return min(dataset_rank_max, max(base, from_zoom))


def label_for_lod_level(level: int) -> str:
    level = clamp_lod_level(level)
    if level == 1:
        return "Sparse"
    if level == DEFAULT_LOD_LEVEL:
        return "Balanced"
    if level == LOD_CURVE_STEP_COUNT:
        return "Dense"
    if level == LOD_ALL_LEVEL:
        return "All"
    return f"Level {level}"

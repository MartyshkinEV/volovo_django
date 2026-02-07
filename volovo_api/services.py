from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from tracking.models import TrackPoint

# ---- Пескобаза (погрузка) ----
SAND_BASE_LAT = 52.036242
SAND_BASE_LON = 37.887744
SAND_BASE_RADIUS_KM = 0.02  # 20 м


def parse_tm(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@dataclass
class P:
    lat: float
    lon: float
    tm: str
    tm_dt: datetime
    idx: Optional[int]


def load_points(
    oid: int,
    dt_from: Optional[str],
    dt_to: Optional[str],
    limit: int = 500_000,
) -> List[P]:
    q = TrackPoint.objects.filter(oid=oid)
    df = parse_tm(dt_from)
    dt = parse_tm(dt_to)
    if df:
        q = q.filter(tm__gte=df)
    if dt:
        q = q.filter(tm__lte=dt)

    # idx может быть None; сортируем idx, потом tm
    q = q.order_by("idx", "tm")[:limit]

    out: List[P] = []
    for tp in q.iterator(chunk_size=5000):
        # geography PointField -> x=lon, y=lat
        out.append(
            P(
                lat=float(tp.geom.y),
                lon=float(tp.geom.x),
                tm=tp.tm.strftime("%Y-%m-%d %H:%M:%S"),
                tm_dt=tp.tm,
                idx=tp.idx,
            )
        )
    return out


def gps_filter_jumps(
    points: List[P],
    max_jump_km: float = 1.0,
    max_speed_kmh: float = 180.0,
) -> Tuple[List[P], Dict[str, Any]]:
    n = len(points)
    if n < 2:
        return points, {"original": n, "kept": n, "removed": 0}

    kept = [points[0]]
    removed = 0
    prev = points[0]

    for p in points[1:]:
        d = haversine_km(prev.lat, prev.lon, p.lat, p.lon)

        speed_ok = True
        dt_s = (p.tm_dt - prev.tm_dt).total_seconds()
        if dt_s > 0:
            sp = d / (dt_s / 3600.0)
            if sp > max_speed_kmh:
                speed_ok = False

        if d > max_jump_km or not speed_ok:
            removed += 1
            continue

        kept.append(p)
        prev = p

    return kept, {"original": n, "kept": len(kept), "removed": removed}


def calc_total_km(points: List[P]) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    prev = points[0]
    for p in points[1:]:
        total += haversine_km(prev.lat, prev.lon, p.lat, p.lon)
        prev = p
    return total


def count_sand_base_entries(points: List[P]) -> int:
    inside = False
    entries = 0
    for p in points:
        d = haversine_km(p.lat, p.lon, SAND_BASE_LAT, SAND_BASE_LON)
        if d <= SAND_BASE_RADIUS_KM:
            if not inside:
                entries += 1
                inside = True
        else:
            inside = False
    return entries


def split_trips_from_sand_base(points: List[P]) -> Tuple[List[List[P]], List[int]]:
    """
    Рейс начинается с момента въезда на пескобазу (outside->inside),
    и длится до следующего въезда.
    """
    n = len(points)
    if n == 0:
        return [], []

    inside_prev = False
    entry_indexes: List[int] = []
    for i, p in enumerate(points):
        d = haversine_km(p.lat, p.lon, SAND_BASE_LAT, SAND_BASE_LON)
        inside = d <= SAND_BASE_RADIUS_KM
        if inside and not inside_prev:
            entry_indexes.append(i)
        inside_prev = inside

    if not entry_indexes:
        return [points], []

    trips: List[List[P]] = []
    for k, start_i in enumerate(entry_indexes):
        end_i = entry_indexes[k + 1] if k + 1 < len(entry_indexes) else n
        seg = points[start_i:end_i]
        if len(seg) >= 2:
            trips.append(seg)

    return trips, entry_indexes


def slim_points(points: List[P], max_points: int) -> Tuple[List[P], int]:
    n = len(points)
    if n <= max_points:
        return points, 1
    step = max(1, n // max_points)
    out = points[::step]
    if out and out[-1].tm != points[-1].tm:
        out.append(points[-1])
    return out, step

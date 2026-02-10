from __future__ import annotations
from django.db.models.functions import Cast
from django.contrib.gis.db.models import GeometryField

import json
from datetime import datetime
from math import radians, sin, cos, asin, sqrt
from uuid import uuid4

from django.conf import settings
from django.db.models import F, Func, FloatField
from django.http import HttpResponse, JsonResponse
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.contrib.gis.db.models.functions import Transform

from tracking.models import RouteCatalog, TrackPoint


# ----------------- PostGIS helpers (ST_X / ST_Y) -----------------

class ST_X(Func):
    function = "ST_X"
    output_field = FloatField()


class ST_Y(Func):
    function = "ST_Y"
    output_field = FloatField()


# ----------------- utils -----------------

def _iso_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _dt(s: str):
    """JS шлёт dt_from/dt_to как строки (обычно ISO)."""
    if not s:
        return None
    s = s.strip()
    return parse_datetime(s)


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Расстояние по сфере, км."""
    R = 6371.0088
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return R * c


def _get_sand_base():
    lat = getattr(settings, "SAND_BASE_LAT", None)
    lon = getattr(settings, "SAND_BASE_LON", None)
    radius_km = getattr(settings, "SAND_BASE_RADIUS_KM", None)
    if lat is None or lon is None or radius_km is None:
        return None
    try:
        return {"lat": float(lat), "lon": float(lon), "radius_km": float(radius_km)}
    except Exception:
        return None


def _total_km(points) -> float:
    if len(points) < 2:
        return 0.0
    km = 0.0
    prev = points[0]
    for p in points[1:]:
        km += _haversine_km(prev["lat"], prev["lon"], p["lat"], p["lon"])
        prev = p
    return km


def _sand_base_entries(points, sb):
    """
    Считаем "заезды" на пескобазу как переход из вне -> внутрь радиуса.
    Возвращаем entries_count и список индексов точек-входа.
    """
    if not sb or not points:
        return 0, []
    lat0, lon0, r = sb["lat"], sb["lon"], sb["radius_km"]

    inside_prev = False
    entries = 0
    entry_idx = []

    for i, p in enumerate(points):
        d = _haversine_km(lat0, lon0, p["lat"], p["lon"])
        inside = d <= r
        if inside and not inside_prev:
            entries += 1
            entry_idx.append(i)
        inside_prev = inside

    return entries, entry_idx


def _downsample(points, max_points: int):
    if max_points <= 0 or len(points) <= max_points:
        return points
    step = max(1, len(points) // max_points)
    sampled = points[::step]
    if sampled and sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled


def _filter_points(points, max_jump_km: float, max_speed_kmh: float):
    """
    Фильтрация:
    - выкидываем точки с speed > max_speed_kmh (если speed есть)
    - выкидываем "скачки" где дистанция между соседями > max_jump_km
    Возвращаем: filtered_points, jumps_removed, original_count
    """
    original_count = len(points)
    if original_count <= 1:
        return points, 0, original_count

    # 1) speed filter
    speed_filtered = []
    for p in points:
        sp = p.get("speed")
        if sp is None:
            speed_filtered.append(p)
        else:
            try:
                if float(sp) <= max_speed_kmh:
                    speed_filtered.append(p)
            except Exception:
                speed_filtered.append(p)

    # 2) jump filter
    out = []
    jumps_removed = 0
    prev = None

    for p in speed_filtered:
        if prev is None:
            out.append(p)
            prev = p
            continue

        d = _haversine_km(prev["lat"], prev["lon"], p["lat"], p["lon"])
        if d > max_jump_km:
            jumps_removed += 1
            # не принимаем эту точку, prev оставляем
            continue

        out.append(p)
        prev = p

    return out, jumps_removed, original_count


def _load_points(oid: int, dt_from, dt_to):
    qs = TrackPoint.objects.filter(oid=oid)

    if dt_from:
        qs = qs.filter(tm__gte=dt_from)
    if dt_to:
        qs = qs.filter(tm__lte=dt_to)

    # geography -> geometry (в 4326), затем ST_X/ST_Y
    qs = qs.annotate(
        geom2=Cast("geom", GeometryField(srid=4326)),
    ).annotate(
        lon=ST_X(F("geom2")),
        lat=ST_Y(F("geom2")),
    )

    rows = list(qs.order_by("tm").values("tm", "lat", "lon"))
    for r in rows:
        r["speed"] = None
    return rows



# ----------------- API endpoints -----------------

@require_GET
def routes(request):
    qs = (
        RouteCatalog.objects
        .all()
        .order_by("name")
        .values("name", "road_width_m", "road_length_km", "pss_tonnage_t")
    )
    return JsonResponse({"routes": list(qs)})


@require_GET
def oids(request):
    qs = (
        TrackPoint.objects
        .values_list("oid", flat=True)
        .distinct()
        .order_by("oid")
    )
    return JsonResponse({"oids": list(qs)})


@require_GET
def points_summary(request):
    """
    JS ждёт:
      oid, dt_from, dt_to,
      points_count_used, gps_jumps_removed,
      total_km,
      sand_base_entries
    """
    try:
        oid = int(request.GET.get("oid", "0") or 0)
        max_jump_km = float(request.GET.get("max_jump_km", "1.0") or 1.0)
        max_speed_kmh = float(request.GET.get("max_speed_kmh", "180") or 180.0)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)

    dt_from = _dt(request.GET.get("dt_from", ""))
    dt_to = _dt(request.GET.get("dt_to", ""))

    points = _load_points(oid, dt_from, dt_to)
    filtered, jumps_removed, original_count = _filter_points(points, max_jump_km, max_speed_kmh)

    sb = _get_sand_base()
    entries, _ = _sand_base_entries(filtered, sb)

    return JsonResponse({
        "oid": oid,
        "dt_from": request.GET.get("dt_from", "") or "",
        "dt_to": request.GET.get("dt_to", "") or "",
        "original_count": original_count,
        "points_count_used": len(filtered),
        "gps_jumps_removed": jumps_removed,
        "total_km": round(_total_km(filtered), 6),
        "sand_base_entries": entries,
    })


@require_GET
def trips_for_map(request):
    """
    JS ждёт:
      trips_count, sand_base (опц), sand_base_entries,
      original_count, filtered_count, gps_jumps_removed,
      trips: [{trip_no, tm_start, tm_end, distance_km, points:[{lat,lon}]}]
    """
    try:
        oid = int(request.GET.get("oid", "0") or 0)
        max_points_per_trip = int(request.GET.get("max_points_per_trip", "2000") or 2000)
        max_jump_km = float(request.GET.get("max_jump_km", "1.0") or 1.0)
        max_speed_kmh = float(request.GET.get("max_speed_kmh", "180") or 180.0)
        min_trip_km = float(request.GET.get("min_trip_km", "1.0") or 1.0)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)

    dt_from = _dt(request.GET.get("dt_from", ""))
    dt_to = _dt(request.GET.get("dt_to", ""))

    points = _load_points(oid, dt_from, dt_to)
    filtered, jumps_removed, original_count = _filter_points(points, max_jump_km, max_speed_kmh)

    sb = _get_sand_base()
    entries_count, entry_idx = _sand_base_entries(filtered, sb)

    trips = []

    # Деление на рейсы:
    # - если есть >=2 заезда, делим по промежуткам между заездами
    # - если <2 заездов, отдаём 1 рейс целиком (чтобы карта хоть что-то рисовала)
    segments = []
    if len(entry_idx) >= 2:
        for a, b in zip(entry_idx[:-1], entry_idx[1:]):
            if b > a:
                segments.append((a, b))
    else:
        if len(filtered) >= 2:
            segments.append((0, len(filtered) - 1))

    trip_no = 1
    for a, b in segments:
        seg = filtered[a:b + 1]
        km = _total_km(seg)
        if km < min_trip_km:
            continue

        seg2 = _downsample(seg, max_points_per_trip)

        tm_start = seg2[0]["tm"].isoformat() if seg2 and seg2[0].get("tm") else ""
        tm_end = seg2[-1]["tm"].isoformat() if seg2 and seg2[-1].get("tm") else ""

        trips.append({
            "trip_no": trip_no,
            "tm_start": tm_start,
            "tm_end": tm_end,
            "distance_km": round(km, 6),
            "points": [{"lat": p["lat"], "lon": p["lon"]} for p in seg2],
        })
        trip_no += 1

    return JsonResponse({
        "oid": oid,
        "dt_from": request.GET.get("dt_from", "") or "",
        "dt_to": request.GET.get("dt_to", "") or "",
        "trips_count": len(trips),
        "sand_base": sb,
        "sand_base_entries": entries_count,
        "original_count": original_count,
        "filtered_count": len(filtered),
        "gps_jumps_removed": jumps_removed,
        "trips": trips,
    })


# ----------------- forms / export -----------------

@csrf_exempt
@require_POST
def forms_save(request):
    """
    JS ожидает: {"form_id": "..."}
    Пока заглушка: возвращаем случайный id.
    """
    try:
        _payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse({"error": "invalid json"}, status=400)

    form_id = str(uuid4())
    return JsonResponse({"form_id": form_id})


@require_GET
def forms_export_xlsx(request, form_id: str):
    """
    JS ждёт файл (blob). Пока отдаём пустышку.
    """
    content = b""
    resp = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="putevoy-{form_id}.xlsx"'
    return resp

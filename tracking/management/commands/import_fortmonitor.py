import re
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from typing import Optional, Any, Dict, List, Tuple

import requests

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.contrib.gis.geos import Point

from tracking.models import TrackPoint


BASE = "http://109.195.2.91"

# куда сохранять cookie
DOCS = Path.home() / "Документы"
COOKIE_TXT = DOCS / "cookie.txt"

# учётка Fortmonitor (лучше потом вынести в env)
LOGIN = "volovo"
PASSWORD = "Vol170717"


def _hidden(html: str, name: str) -> Optional[str]:
    m = re.search(
        r'<input[^>]+name="{name}"[^>]+value="([^"]*)"'.format(name=re.escape(name)),
        html,
        re.IGNORECASE,
    )
    return m.group(1) if m else None


def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        if isinstance(x, str):
            x = x.replace(",", ".").strip()
            if x == "":
                return None
        return float(x)
    except Exception:
        return None


def _parse_tm(tm_raw: Any) -> Optional[datetime]:
    """
    Fortmonitor 'tm' обычно строка.
    Возвращаем aware datetime в TZ проекта (обычно Europe/Moscow/+03).
    """
    if tm_raw is None:
        return None

    if isinstance(tm_raw, datetime):
        dt = tm_raw
    else:
        s = str(tm_raw).strip()
        if not s:
            return None

        fmts = [
            "%Y-%m-%d %H:%M:%S",
            "%d.%m.%Y %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d.%m.%Y %H:%M",
        ]

        dt = None
        for fmt in fmts:
            try:
                dt = datetime.strptime(s, fmt)
                break
            except Exception:
                continue

        if dt is None:
            return None

    tz = timezone.get_current_timezone()
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, tz)
    else:
        dt = dt.astimezone(tz)
    return dt


def normalize_dt_str(s: str, is_to: bool) -> str:
    """
    Принимаем:
      YYYY-MM-DD
      YYYY-MM-DD HH:MM:SS
    Возвращаем: 'YYYY-MM-DD HH:MM:SS'
    """
    s = (s or "").strip()
    if not s:
        raise RuntimeError("Пустая дата")

    if len(s) == 10:
        return s + (" 23:59:59" if is_to else " 00:00:00")
    return s


def split_range(dt_from: datetime, dt_to: datetime, chunk_hours: int):
    cur = dt_from
    step = timedelta(hours=chunk_hours)
    while cur < dt_to:
        nxt = min(dt_to, cur + step)
        yield cur, nxt
        cur = nxt


def dst_to_odo_km(dst_val: Any) -> Optional[float]:
    """
    Fortmonitor coords[][]: второй элемент обычно 'dst' (пройдено).
    Иногда в метрах, иногда в км.
    Эвристика:
      если > 10000 => метры -> км
      иначе => км
    """
    d = _to_float(dst_val)
    if d is None:
        return None
    if d > 10000:
        return d / 1000.0
    return d


def login_get_cookie() -> str:
    """
    Логин на login.aspx (ASP.NET) и сохранение cookie.
    """
    s = requests.Session()

    r = s.get("{}/login.aspx".format(BASE), timeout=60)
    r.raise_for_status()
    html = r.text

    viewstate = _hidden(html, "__VIEWSTATE")
    eventvalidation = _hidden(html, "__EVENTVALIDATION")
    viewstategenerator = _hidden(html, "__VIEWSTATEGENERATOR")

    if not viewstate:
        raise RuntimeError("Не нашёл __VIEWSTATE на login.aspx — возможно форма изменилась.")

    data = {
        "__EVENTTARGET": "lbEnter",
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        "__VIEWSTATE": viewstate,
        "__EVENTVALIDATION": eventvalidation or "",
        "__VIEWSTATEGENERATOR": viewstategenerator or "",
        "TimeZone": "3",
        "tbLogin": LOGIN,
        "tbPassword": PASSWORD,
    }

    r2 = s.post("{}/login.aspx".format(BASE), data=data, timeout=60, allow_redirects=True)
    r2.raise_for_status()

    cookie_line = "; ".join(["{}={}".format(c.name, c.value) for c in s.cookies])
    if not cookie_line:
        raise RuntimeError("Cookie пустые — логин не удался?")

    COOKIE_TXT.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_TXT.write_text(cookie_line, encoding="utf-8")
    return cookie_line


def fetch_track(cookie_line: str, oid: int, dt_from: str, dt_to: str) -> Dict[str, Any]:
    url = (
        "{}/api/Api.svc/track?oid={}&from={}&to={}".format(
            BASE, oid, quote(dt_from), quote(dt_to)
        )
    )
    r = requests.get(
        url,
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "{}/MileageReportData.aspx".format(BASE),
            "Cookie": cookie_line,
            "User-Agent": "Mozilla/5.0",
        },
        timeout=90,
    )
    r.raise_for_status()
    return r.json()


class Command(BaseCommand):
    help = "Импорт трек-точек из Fortmonitor в Postgres/PostGIS (tracking_trackpoint) с заполнением odo_km из dst."

    def add_arguments(self, parser):
        parser.add_argument("--oid", type=int, default=0, help="Один OID")
        parser.add_argument("--oids", type=str, default="", help="Список OID через запятую: 182,716,717")
        parser.add_argument("--from", dest="dt_from", required=True, help="Начало: YYYY-MM-DD или YYYY-MM-DD HH:MM:SS")
        parser.add_argument("--to", dest="dt_to", required=True, help="Конец: YYYY-MM-DD или YYYY-MM-DD HH:MM:SS")
        parser.add_argument("--chunk-hours", type=int, default=6, help="Размер чанка в часах")
        parser.add_argument("--no-login", action="store_true", help="Не логиниться, взять cookie из cookie.txt")
        parser.add_argument("--save-raw", action="store_true", help="Сохранять raw json ответы в ~/Документы")

    @transaction.atomic
    def handle(self, *args, **opts):
        # 1) OIDs
        oids: List[int] = []
        if int(opts.get("oid") or 0):
            oids = [int(opts["oid"])]
        else:
            s = (opts.get("oids") or "").strip()
            if s:
                oids = [int(x.strip()) for x in s.split(",") if x.strip().isdigit()]

        if not oids:
            raise RuntimeError("Нужно указать --oid или --oids")

        # 2) Dates
        dt_from_str = normalize_dt_str(opts["dt_from"], is_to=False)
        dt_to_str = normalize_dt_str(opts["dt_to"], is_to=True)

        dt_from = _parse_tm(dt_from_str)
        dt_to = _parse_tm(dt_to_str)
        if not dt_from or not dt_to:
            raise RuntimeError("Не смог распарсить даты. Пример: --from '2025-12-09' --to '2026-02-10'")

        chunk_hours = int(opts.get("chunk_hours") or 6)

        self.stdout.write("Диапазон: {} -> {} (chunk={}h)".format(dt_from_str, dt_to_str, chunk_hours))
        self.stdout.write("OIDs: {}".format(oids))

        # 3) Cookie
        if opts.get("no_login"):
            cookie_line = COOKIE_TXT.read_text(encoding="utf-8").strip() if COOKIE_TXT.exists() else ""
            if not cookie_line:
                raise RuntimeError("cookie.txt пустой или не найден. Убери --no-login или залогинься.")
        else:
            self.stdout.write("Логин в Fortmonitor...")
            cookie_line = login_get_cookie()
            self.stdout.write("Cookie сохранены: {}".format(COOKIE_TXT))

        total_new = 0
        total_upd = 0

        for oid in oids:
            # индекс для новых точек
            cur_max_idx = (
                TrackPoint.objects.filter(oid=oid)
                .exclude(idx__isnull=True)
                .order_by("-idx")
                .values_list("idx", flat=True)
                .first()
            )
            next_idx = int(cur_max_idx) + 1 if cur_max_idx is not None else 0

            self.stdout.write(self.style.MIGRATE_HEADING("\nOID={} стартовый idx={}".format(oid, next_idx)))

            for a, b in split_range(dt_from, dt_to, chunk_hours):
                a_str = a.strftime("%Y-%m-%d %H:%M:%S")
                b_str = b.strftime("%Y-%m-%d %H:%M:%S")

                data = fetch_track(cookie_line, oid, a_str, b_str)

                if opts.get("save_raw"):
                    out = DOCS / "track_{}_{}_{}.json".format(
                        oid, a.strftime("%Y%m%d_%H%M%S"), b.strftime("%Y%m%d_%H%M%S")
                    )
                    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

                coords = data.get("coords") or []
                if not coords:
                    self.stdout.write("  {} -> {}: 0 точек".format(a_str, b_str))
                    continue

                existing = set(
                    TrackPoint.objects.filter(oid=oid, tm__gte=a, tm__lt=b)
                    .values_list("tm", flat=True)
                )

                new_objs: List[TrackPoint] = []
                upd_rows: List[Tuple[datetime, Point, Optional[float], Optional[float]]] = []

                for row in coords:
                    # ожидаем list: [dir, dst, lat, lon, speed, st, tm, width]
                    if isinstance(row, list):
                        dst_ = row[1] if len(row) > 1 else None
                        lat_ = _to_float(row[2] if len(row) > 2 else None)
                        lon_ = _to_float(row[3] if len(row) > 3 else None)
                        speed_ = _to_float(row[4] if len(row) > 4 else None)
                        tm_raw = row[6] if len(row) > 6 else None
                    elif isinstance(row, dict):
                        dst_ = row.get("dst")
                        lat_ = _to_float(row.get("lat"))
                        lon_ = _to_float(row.get("lon"))
                        speed_ = _to_float(row.get("speed"))
                        tm_raw = row.get("tm")
                    else:
                        continue

                    if lat_ is None or lon_ is None:
                        continue

                    tm_dt = _parse_tm(tm_raw)
                    if not tm_dt:
                        continue

                    geom = Point(float(lon_), float(lat_), srid=4326)

                    odo_km = dst_to_odo_km(dst_)

                    if tm_dt in existing:
                        upd_rows.append((tm_dt, geom, speed_, odo_km))
                    else:
                        new_objs.append(
                            TrackPoint(
                                oid=oid,
                                tm=tm_dt,
                                idx=next_idx,
                                geom=geom,
                                speed_kmh=speed_,
                                odo_km=odo_km,
                            )
                        )
                        next_idx += 1

                if new_objs:
                    TrackPoint.objects.bulk_create(new_objs, batch_size=5000)
                    total_new += len(new_objs)

                # обновляем существующие
                if upd_rows:
                    tms = [x[0] for x in upd_rows]
                    objs = list(TrackPoint.objects.filter(oid=oid, tm__in=tms))
                    by_tm = {o.tm: o for o in objs}

                    touched = 0
                    for tm_dt, geom, speed_, odo_km in upd_rows:
                        o = by_tm.get(tm_dt)
                        if not o:
                            continue

                        changed = False
                        if geom and o.geom != geom:
                            o.geom = geom
                            changed = True
                        if speed_ is not None and o.speed_kmh != speed_:
                            o.speed_kmh = speed_
                            changed = True
                        if odo_km is not None and o.odo_km != odo_km:
                            o.odo_km = odo_km
                            changed = True

                        if changed:
                            touched += 1

                    if touched:
                        TrackPoint.objects.bulk_update(objs, ["geom", "speed_kmh", "odo_km"], batch_size=5000)
                        total_upd += touched

                self.stdout.write(
                    "  {} -> {}: coords={} new={} upd={}".format(
                        a_str, b_str, len(coords), len(new_objs), len(upd_rows)
                    )
                )

        self.stdout.write(self.style.SUCCESS("\nГОТОВО. new={}, updated={}".format(total_new, total_upd)))

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand

from pymongo import MongoClient, ASCENDING

from tracking.models import TrackPoint, RouteCatalog


MONGO_URI = "mongodb://127.0.0.1:27017"
DB_NAME = "volovo"
COL_POINTS = "track_points"
COL_ROUTES = "routes_catalog"


def to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        try:
            return float(str(v).replace(",", "."))
        except Exception:
            return None


def parse_tm(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


class Command(BaseCommand):
    help = "Import MongoDB collections routes_catalog + track_points into PostGIS (RouteCatalog, TrackPoint)."

    def add_arguments(self, parser):
        parser.add_argument("--drop", action="store_true", help="Delete existing data before import")
        parser.add_argument("--batch", type=int, default=5000, help="Bulk insert batch size")
        parser.add_argument("--limit", type=int, default=0, help="Limit points (0=all)")
        parser.add_argument("--oid", type=int, default=0, help="Import only this oid (0=all)")

    def handle(self, *args, **opts):
        drop = bool(opts["drop"])
        batch = int(opts["batch"])
        limit = int(opts["limit"])
        only_oid = int(opts["oid"])

        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        points_col = db[COL_POINTS]
        routes_col = db[COL_ROUTES]

        if drop:
            self.stdout.write(self.style.WARNING("Dropping RouteCatalog + TrackPoint..."))
            RouteCatalog.objects.all().delete()
            TrackPoint.objects.all().delete()

        # ---- Routes
        self.stdout.write("Importing routes_catalog...")
        routes = list(
            routes_col.find(
                {},
                {"_id": 0, "name": 1, "road_width_m": 1, "road_length_km": 1, "pss_tonnage_t": 1},
            ).sort([("name", ASCENDING)])
        )

        rc_objs = []
        for r in routes:
            name = (r.get("name") or "").strip()
            if not name:
                continue
            rc_objs.append(
                RouteCatalog(
                    name=name,
                    road_width_m=to_float(r.get("road_width_m")),
                    road_length_km=to_float(r.get("road_length_km")),
                    pss_tonnage_t=to_float(r.get("pss_tonnage_t")),
                )
            )

        RouteCatalog.objects.bulk_create(rc_objs, ignore_conflicts=True, batch_size=2000)
        self.stdout.write(self.style.SUCCESS(f"routes_catalog imported: {len(rc_objs)}"))

        # ---- Points
        self.stdout.write("Importing track_points...")
        q: Dict[str, Any] = {}
        if only_oid:
            q["oid"] = only_oid

        cur = points_col.find(q, {"_id": 0, "oid": 1, "lat": 1, "lon": 1, "tm": 1, "idx": 1}).sort(
            [("oid", ASCENDING), ("idx", ASCENDING), ("tm", ASCENDING)]
        )
        if limit and limit > 0:
            cur = cur.limit(limit)

        buf: List[TrackPoint] = []
        inserted = 0
        skipped = 0

        def flush():
            nonlocal inserted, buf
            if not buf:
                return
            TrackPoint.objects.bulk_create(buf, batch_size=batch)
            inserted += len(buf)
            buf = []
            self.stdout.write(f"  inserted: {inserted}", ending="\r")

        for p in cur:
            oid = p.get("oid")
            lat = to_float(p.get("lat"))
            lon = to_float(p.get("lon"))
            tm = parse_tm(p.get("tm"))
            if oid is None or lat is None or lon is None or tm is None:
                skipped += 1
                continue

            idx = p.get("idx")
            try:
                idx = int(idx) if idx is not None else None
            except Exception:
                idx = None

            geom = Point(float(lon), float(lat), srid=4326)
            buf.append(TrackPoint(oid=int(oid), tm=tm, idx=idx, geom=geom))

            if len(buf) >= batch:
                flush()

        flush()
        self.stdout.write("")  # newline
        self.stdout.write(self.style.SUCCESS(f"track_points imported: inserted={inserted}, skipped={skipped}"))


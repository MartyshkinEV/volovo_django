from django.contrib.gis.db import models as gis_models
from django.db import models

class RouteCatalog(models.Model):
    name = models.CharField(max_length=255, unique=True)
    road_width_m = models.FloatField(null=True, blank=True)
    road_length_km = models.FloatField(null=True, blank=True)
    pss_tonnage_t = models.FloatField(null=True, blank=True)

    def __str__(self):
        return self.name


class TrackPoint(gis_models.Model):
    oid = models.IntegerField(db_index=True)
    tm = models.DateTimeField(db_index=True)
    idx = models.IntegerField(db_index=True, null=True, blank=True)

    # lon/lat
    geom = gis_models.PointField(srid=4326, geography=True)

    class Meta:
        indexes = [
            models.Index(fields=["oid", "idx"]),
            models.Index(fields=["oid", "tm"]),
        ]


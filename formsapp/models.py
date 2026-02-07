from django.db import models


class PutevoyForm(models.Model):
    mongo_id = models.CharField(max_length=64, unique=True, null=True, blank=True)  # _id из Mongo как строка
    oid = models.IntegerField(db_index=True, null=True, blank=True)

    dt_from = models.DateTimeField(null=True, blank=True)
    dt_to = models.DateTimeField(null=True, blank=True)

    payload = models.JSONField(null=True, blank=True)  # ВСЯ форма как есть: meta/totals/rows
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "putevoy_forms"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Form #{self.id} oid={self.oid}"



class PutevoyFormRow(models.Model):
    form = models.ForeignKey(PutevoyForm, on_delete=models.CASCADE, related_name="rows")

    trip_no = models.IntegerField()
    route = models.CharField(max_length=255, blank=True)

    km = models.FloatField(default=0)
    tons = models.FloatField(default=0)
    width = models.FloatField(null=True, blank=True)
    length = models.FloatField(null=True, blank=True)
    pss_tonnage = models.FloatField(null=True, blank=True)
    delivery = models.FloatField(default=0)

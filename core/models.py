from decimal import Decimal
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Sum
from django.utils import timezone

# ---- Products ----------------------------------------------------------
SORTEX, NORMAL, RAW, OIL, WASTE = "sortex", "normal", "raw", "oil", "waste"
SEEDS = [SORTEX, NORMAL, RAW]
PRODUCT_LABELS = {
    SORTEX: "Sortex cleaned", NORMAL: "Normal cleaned", RAW: "Raw",
    OIL: "Oil", WASTE: "Waste / cake",
}
PRODUCT_CHOICES = list(PRODUCT_LABELS.items())
UNIT = {SORTEX: "kg", NORMAL: "kg", RAW: "kg", OIL: "L", WASTE: "kg"}

ZERO = Decimal("0")


class Franchise(models.Model):
    name = models.CharField(max_length=120)
    city = models.CharField(max_length=80)
    address = models.TextField(blank=True)
    contact_name = models.CharField(max_length=80, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.city})"


class User(AbstractUser):
    SUPER, FACTORY, F_MAIN, F_SUB = "super", "factory", "fmain", "fsub"
    ROLES = [
        (SUPER, "Super Admin"), (FACTORY, "Factory Sub Admin"),
        (F_MAIN, "Franchise Main Admin"), (F_SUB, "Franchise Sub Admin"),
    ]
    role = models.CharField(max_length=10, choices=ROLES, default=SUPER)
    franchise = models.ForeignKey(Franchise, null=True, blank=True,
                                  on_delete=models.PROTECT, related_name="users")

    @property
    def is_franchise_user(self):
        return self.role in (self.F_MAIN, self.F_SUB)


class LocalShop(models.Model):
    name = models.CharField(max_length=120)
    place = models.CharField(max_length=80, blank=True)
    phone = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# ---- Stock ledger ------------------------------------------------------
class StockMovement(models.Model):
    """Every stock change is a row here. franchise=None means the factory."""
    date = models.DateField(default=timezone.localdate)
    franchise = models.ForeignKey(Franchise, null=True, blank=True, on_delete=models.PROTECT)
    product = models.CharField(max_length=10, choices=PRODUCT_CHOICES)
    qty = models.DecimalField(max_digits=12, decimal_places=2)  # + in, - out
    reason = models.CharField(max_length=60)
    ref = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


def stock_for(franchise=None):
    """Return {product: qty} for the factory (None) or a franchise."""
    rows = (StockMovement.objects.filter(franchise=franchise)
            .values("product").annotate(t=Sum("qty")))
    out = {p: ZERO for p in PRODUCT_LABELS}
    for r in rows:
        out[r["product"]] = r["t"] or ZERO
    return out


def move(franchise, product, qty, reason, ref="", date=None):
    return StockMovement.objects.create(
        franchise=franchise, product=product, qty=qty, reason=reason, ref=ref,
        date=date or timezone.localdate())


# ---- Factory intake ----------------------------------------------------
class InwardLoad(models.Model):
    date = models.DateField(default=timezone.localdate)
    supplier = models.CharField(max_length=120)
    vehicle_no = models.CharField(max_length=30, blank=True)
    total_kg = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.CharField(max_length=200, blank=True)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    @property
    def classified_kg(self):
        return self.items.aggregate(t=Sum("qty_kg"))["t"] or ZERO

    @property
    def wastage_kg(self):
        return self.total_kg - self.classified_kg


class InwardItem(models.Model):
    load = models.ForeignKey(InwardLoad, on_delete=models.CASCADE, related_name="items")
    product = models.CharField(max_length=10, choices=PRODUCT_CHOICES)
    qty_kg = models.DecimalField(max_digits=12, decimal_places=2)


# ---- Transfers ---------------------------------------------------------
class Transfer(models.Model):
    SENT, CONFIRMED, MISMATCH, RESOLVED = "sent", "confirmed", "mismatch", "resolved"
    STATUS = [(SENT, "Sent"), (CONFIRMED, "Confirmed"), (MISMATCH, "Mismatch"), (RESOLVED, "Resolved")]
    date = models.DateField(default=timezone.localdate)
    franchise = models.ForeignKey(Franchise, null=True, blank=True, on_delete=models.PROTECT)
    local_shop = models.ForeignKey(LocalShop, null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=10, choices=STATUS, default=SENT)
    note = models.CharField(max_length=200, blank=True)
    resolution_note = models.CharField(max_length=200, blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.PROTECT, related_name="+")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    @property
    def destination(self):
        return str(self.franchise or self.local_shop)

    @property
    def is_franchise(self):
        return self.franchise_id is not None


class TransferItem(models.Model):
    transfer = models.ForeignKey(Transfer, on_delete=models.CASCADE, related_name="items")
    product = models.CharField(max_length=10, choices=PRODUCT_CHOICES)
    qty_sent = models.DecimalField(max_digits=12, decimal_places=2)
    qty_received = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    @property
    def difference(self):
        if self.qty_received is None:
            return None
        return self.qty_received - self.qty_sent


# ---- Franchise operations ---------------------------------------------
class Sale(models.Model):
    date = models.DateField(default=timezone.localdate)
    franchise = models.ForeignKey(Franchise, on_delete=models.PROTECT)
    customer = models.CharField(max_length=120, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    billed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.CharField(max_length=10, choices=PRODUCT_CHOICES)
    qty = models.DecimalField(max_digits=12, decimal_places=2)
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)


class OilExtraction(models.Model):
    date = models.DateField(default=timezone.localdate)
    franchise = models.ForeignKey(Franchise, on_delete=models.PROTECT)
    seed_product = models.CharField(max_length=10, choices=[(p, PRODUCT_LABELS[p]) for p in SEEDS])
    seed_used = models.DecimalField(max_digits=12, decimal_places=2)
    oil_litres = models.DecimalField(max_digits=12, decimal_places=2)
    waste_kg = models.DecimalField(max_digits=12, decimal_places=2)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]


class WasteReturn(models.Model):
    SENT, RECEIVED = "sent", "received"
    date = models.DateField(default=timezone.localdate)
    franchise = models.ForeignKey(Franchise, on_delete=models.PROTECT)
    qty_kg = models.DecimalField(max_digits=12, decimal_places=2)
    rate_per_kg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=10, default=SENT)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

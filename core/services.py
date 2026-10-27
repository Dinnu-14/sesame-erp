"""Business rules. Views stay thin; all stock changes go through here."""
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from . import models as m
from .models import ZERO, stock_for, move


class RuleError(Exception):
    """A business rule was broken; the message is shown to the user."""


def _label(p):
    return m.PRODUCT_LABELS[p]


def _clean(qtys):
    return {p: Decimal(q) for p, q in qtys.items() if q and Decimal(q) > 0}


def _check_stock(franchise, needs):
    have = stock_for(franchise)
    for p, q in needs.items():
        if have[p] < q:
            raise RuleError(
                f"Not enough {_label(p)} in stock: have {have[p]:.2f} {m.UNIT[p]}, need {q:.2f}.")


@transaction.atomic
def record_inward(user, date, supplier, vehicle_no, total_kg, notes, qtys):
    qtys = _clean(qtys)
    if not qtys:
        raise RuleError("Enter the quantity for at least one variant.")
    if sum(qtys.values()) > total_kg:
        raise RuleError("Variant quantities add up to more than the total load received.")
    load = m.InwardLoad.objects.create(
        date=date, supplier=supplier, vehicle_no=vehicle_no, total_kg=total_kg,
        notes=notes, entered_by=user)
    for p, q in qtys.items():
        m.InwardItem.objects.create(load=load, product=p, qty_kg=q)
        move(None, p, q, "Inward load", f"load:{load.id}", date)
    return load


@transaction.atomic
def create_transfer(user, date, franchise, local_shop, qtys, note=""):
    if bool(franchise) == bool(local_shop):
        raise RuleError("Choose either a franchise or a local shop.")
    qtys = _clean(qtys)
    if not qtys:
        raise RuleError("Enter a quantity for at least one variant.")
    _check_stock(None, qtys)
    direct = local_shop is not None
    t = m.Transfer.objects.create(
        date=date, franchise=franchise, local_shop=local_shop, note=note, sent_by=user,
        status=m.Transfer.CONFIRMED if direct else m.Transfer.SENT)
    for p, q in qtys.items():
        m.TransferItem.objects.create(
            transfer=t, product=p, qty_sent=q, qty_received=q if direct else None)
        move(None, p, -q, "Direct sale to shop" if direct else "Transfer out", f"transfer:{t.id}", date)
    return t


@transaction.atomic
def confirm_transfer(user, transfer, received):
    t = m.Transfer.objects.select_for_update().get(pk=transfer.pk)
    if t.status != m.Transfer.SENT:
        raise RuleError("This transfer has already been confirmed.")
    if not t.franchise_id or t.franchise_id != user.franchise_id:
        raise RuleError("This transfer is not for your franchise.")
    mismatch = False
    for item in t.items.all():
        q = Decimal(received.get(item.id, ZERO) or 0)
        if q < 0:
            raise RuleError("Received quantity cannot be negative.")
        item.qty_received = q
        item.save()
        if q != item.qty_sent:
            mismatch = True
        if q > 0:
            move(t.franchise, item.product, q, "Transfer received", f"transfer:{t.id}")
    t.status = m.Transfer.MISMATCH if mismatch else m.Transfer.CONFIRMED
    t.confirmed_by = user
    t.confirmed_at = timezone.now()
    t.save()
    return t


def resolve_transfer(transfer, note):
    if transfer.status != m.Transfer.MISMATCH:
        raise RuleError("Only mismatched transfers can be resolved.")
    transfer.status = m.Transfer.RESOLVED
    transfer.resolution_note = note
    transfer.save()


@transaction.atomic
def create_sale(user, date, customer, lines):
    """lines: list of (product, qty, rate)."""
    lines = [(p, Decimal(q), Decimal(r)) for p, q, r in lines if q and Decimal(q) > 0]
    if not lines:
        raise RuleError("Add at least one item to the bill.")
    need = {}
    for p, q, _ in lines:
        need[p] = need.get(p, ZERO) + q
    _check_stock(user.franchise, need)
    sale = m.Sale.objects.create(date=date, franchise=user.franchise, customer=customer, billed_by=user)
    total = ZERO
    for p, q, r in lines:
        amt = (q * r).quantize(Decimal("0.01"))
        total += amt
        m.SaleItem.objects.create(sale=sale, product=p, qty=q, rate=r, amount=amt)
        move(user.franchise, p, -q, "Sale", f"sale:{sale.id}", date)
    sale.total = total
    sale.save()
    return sale


@transaction.atomic
def record_extraction(user, date, seed_product, seed_used, oil_litres, waste_kg):
    if seed_used <= 0:
        raise RuleError("Seed used must be more than zero.")
    _check_stock(user.franchise, {seed_product: seed_used})
    e = m.OilExtraction.objects.create(
        date=date, franchise=user.franchise, seed_product=seed_product,
        seed_used=seed_used, oil_litres=oil_litres, waste_kg=waste_kg, entered_by=user)
    ref = f"extraction:{e.id}"
    move(user.franchise, seed_product, -seed_used, "Oil extraction (seed used)", ref, date)
    if oil_litres > 0:
        move(user.franchise, m.OIL, oil_litres, "Oil extraction (oil)", ref, date)
    if waste_kg > 0:
        move(user.franchise, m.WASTE, waste_kg, "Oil extraction (waste)", ref, date)
    return e


@transaction.atomic
def send_waste(user, date, qty_kg):
    if qty_kg <= 0:
        raise RuleError("Quantity must be more than zero.")
    _check_stock(user.franchise, {m.WASTE: qty_kg})
    w = m.WasteReturn.objects.create(date=date, franchise=user.franchise, qty_kg=qty_kg, sent_by=user)
    move(user.franchise, m.WASTE, -qty_kg, "Waste sent to factory", f"waste:{w.id}", date)
    return w


@transaction.atomic
def receive_waste(user, waste, rate):
    w = m.WasteReturn.objects.select_for_update().get(pk=waste.pk)
    if w.status != m.WasteReturn.SENT:
        raise RuleError("This waste return was already received.")
    w.status = m.WasteReturn.RECEIVED
    w.rate_per_kg = rate
    w.amount = (w.qty_kg * rate).quantize(Decimal("0.01"))
    w.received_by = user
    w.save()
    move(None, m.WASTE, w.qty_kg, "Waste bought back", f"waste:{w.id}")
    return w

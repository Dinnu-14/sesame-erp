import json
from datetime import timedelta
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Sum, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from . import forms as f
from . import models as m
from . import services as svc
from .models import User, stock_for, ZERO

SUPER, FACTORY, F_MAIN, F_SUB = User.SUPER, User.FACTORY, User.F_MAIN, User.F_SUB


def role_required(*roles):
    def deco(view):
        @wraps(view)
        @login_required
        def wrapper(request, *a, **k):
            if request.user.role not in roles:
                raise PermissionDenied
            return view(request, *a, **k)
        return wrapper
    return deco


def _qtys(form):
    return {p: form.cleaned_data.get(f"qty_{p}") for p in m.SEEDS}


def _form_page(request, form, title, back, submit="Save", intro=""):
    return render(request, "core/form.html", {"form": form, "title": title, "back": back,
                                              "submit": submit, "intro": intro})


def _day_sales(qs, days=7):
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    rows = qs.filter(date__gte=start).values("date").annotate(t=Sum("total"))
    by = {r["date"]: float(r["t"] or 0) for r in rows}
    labels = [(start + timedelta(days=i)) for i in range(days)]
    return [d.strftime("%d %b") for d in labels], [by.get(d, 0) for d in labels]


def _sales_totals(qs):
    today = timezone.localdate()
    agg = lambda **kw: qs.filter(**kw).aggregate(t=Sum("total"))["t"] or ZERO
    return {"today": agg(date=today), "week": agg(date__gte=today - timedelta(days=6)),
            "month": agg(date__gte=today - timedelta(days=29))}


@login_required
def home(request):
    u = request.user
    if u.role == SUPER:
        return super_dashboard(request)
    if u.role == FACTORY:
        return factory_dashboard(request)
    return franchise_dashboard(request)


def super_dashboard(request):
    today = timezone.localdate()
    fac = stock_for(None)
    in_transit = {p: ZERO for p in m.PRODUCT_LABELS}
    for it in m.TransferItem.objects.filter(transfer__status=m.Transfer.SENT):
        in_transit[it.product] += it.qty_sent
    received_today = m.InwardLoad.objects.filter(date=today).aggregate(t=Sum("total_kg"))["t"] or ZERO
    received_month = m.InwardLoad.objects.filter(date__gte=today - timedelta(days=29)).aggregate(t=Sum("total_kg"))["t"] or ZERO
    franchises = []
    datasets = []
    labels = []
    for fr in m.Franchise.objects.filter(is_active=True):
        qs = m.Sale.objects.filter(franchise=fr)
        labels, vals = _day_sales(qs)
        datasets.append({"label": fr.name, "data": vals})
        st = stock_for(fr)
        franchises.append({"f": fr, "today": _sales_totals(qs)["today"], "month": _sales_totals(qs)["month"],
                           "seed": sum(st[p] for p in m.SEEDS), "oil": st[m.OIL], "waste": st[m.WASTE]})
    ctx = {
        "fac": fac, "in_transit": in_transit, "received_today": received_today,
        "received_month": received_month, "franchises": franchises,
        "open_mismatch": m.Transfer.objects.filter(status=m.Transfer.MISMATCH).count(),
        "pending": m.Transfer.objects.filter(status=m.Transfer.SENT).count(),
        "chart": json.dumps({"labels": labels, "datasets": datasets}),
        "recent": m.Transfer.objects.select_related("franchise", "local_shop").prefetch_related("items")[:6],
    }
    return render(request, "core/dash_super.html", ctx)


def factory_dashboard(request):
    ctx = {"fac": stock_for(None),
           "pending": m.Transfer.objects.filter(status=m.Transfer.SENT).select_related("franchise"),
           "loads": m.InwardLoad.objects.all()[:5],
           "waste_pending": m.WasteReturn.objects.filter(status=m.WasteReturn.SENT).select_related("franchise")}
    return render(request, "core/dash_factory.html", ctx)


def franchise_dashboard(request):
    fr = request.user.franchise
    qs = m.Sale.objects.filter(franchise=fr)
    labels, vals = _day_sales(qs, 14)
    ctx = {"fr": fr, "stock": stock_for(fr), "totals": _sales_totals(qs),
           "chart": json.dumps({"labels": labels, "datasets": [{"label": "Sales (₹)", "data": vals}]}),
           "incoming": m.Transfer.objects.filter(franchise=fr, status=m.Transfer.SENT).prefetch_related("items"),
           "transfers": m.Transfer.objects.filter(franchise=fr).prefetch_related("items")[:5],
           "extractions": m.OilExtraction.objects.filter(franchise=fr)[:5],
           "today_sales": qs.filter(date=timezone.localdate())}
    return render(request, "core/dash_franchise.html", ctx)


# ---- Super admin ---------------------------------------------------------
@role_required(SUPER)
def franchise_list(request):
    rows = []
    for fr in m.Franchise.objects.all():
        rows.append({"f": fr, "users": fr.users.count()})
    return render(request, "core/franchise_list.html", {"rows": rows})


@role_required(SUPER)
def franchise_edit(request, pk=None):
    inst = get_object_or_404(m.Franchise, pk=pk) if pk else None
    form = f.FranchiseForm(request.POST or None, instance=inst)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Franchise saved.")
        return redirect("franchise_list")
    return _form_page(request, form, "Edit franchise" if inst else "Add franchise", "franchise_list")


@role_required(SUPER)
def user_list(request):
    return render(request, "core/user_list.html", {"users": User.objects.select_related("franchise").order_by("role", "username")})


@role_required(SUPER)
def user_add(request):
    form = f.UserForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "User created.")
        return redirect("user_list")
    return _form_page(request, form, "Add user", "user_list", "Create user",
                      "Franchise Main Admin and Sub Admin need a franchise. Factory and Super Admin do not.")


@role_required(SUPER)
def sales_report(request):
    today = timezone.localdate()
    start = request.GET.get("start") or str(today - timedelta(days=6))
    end = request.GET.get("end") or str(today)
    rows = (m.Sale.objects.filter(date__range=(start, end))
            .values("date", "franchise__name").annotate(total=Sum("total"), bills=Count("id"))
            .order_by("-date", "franchise__name"))
    grand = sum((r["total"] for r in rows), ZERO)
    return render(request, "core/sales_report.html", {"rows": rows, "start": start, "end": end, "grand": grand})


@role_required(SUPER)
def mismatches(request):
    rows = m.Transfer.objects.filter(status__in=[m.Transfer.MISMATCH, m.Transfer.RESOLVED]).select_related("franchise").prefetch_related("items")
    return render(request, "core/mismatches.html", {"rows": rows, "form": f.ResolveForm()})


@role_required(SUPER)
def resolve(request, pk):
    t = get_object_or_404(m.Transfer, pk=pk)
    form = f.ResolveForm(request.POST)
    if request.method == "POST" and form.is_valid():
        try:
            svc.resolve_transfer(t, form.cleaned_data["resolution_note"])
            messages.success(request, "Mismatch resolved.")
        except svc.RuleError as e:
            messages.error(request, str(e))
    return redirect("mismatches")


# ---- Factory -------------------------------------------------------------
@role_required(SUPER, FACTORY)
def stock_view(request):
    return render(request, "core/stock.html", {"fac": stock_for(None)})


@role_required(SUPER, FACTORY)
def inward_list(request):
    return render(request, "core/inward_list.html", {"loads": m.InwardLoad.objects.prefetch_related("items")})


@role_required(FACTORY)
def inward_add(request):
    form = f.InwardForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            svc.record_inward(request.user, d["date"], d["supplier"], d["vehicle_no"], d["total_kg"], d["notes"], _qtys(form))
            messages.success(request, "Load recorded and added to godown stock.")
            return redirect("inward_list")
        except svc.RuleError as e:
            form.add_error(None, str(e))
    return _form_page(request, form, "Receive a load", "inward_list", "Save load",
                      "Enter the total received, then split it into variants. Any difference is recorded as wastage.")


@role_required(SUPER, FACTORY, F_MAIN, F_SUB)
def transfer_list(request):
    qs = m.Transfer.objects.select_related("franchise", "local_shop").prefetch_related("items")
    if request.user.is_franchise_user:
        qs = qs.filter(franchise=request.user.franchise)
    return render(request, "core/transfer_list.html", {"rows": qs[:200]})


@role_required(FACTORY)
def transfer_new(request):
    form = f.TransferForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            svc.create_transfer(request.user, d["date"], d["franchise"], d["local_shop"], _qtys(form), d["note"])
            messages.success(request, "Transfer recorded. Franchise stock updates after they confirm receipt.")
            return redirect("transfer_list")
        except svc.RuleError as e:
            form.add_error(None, str(e))
    st = stock_for(None)
    intro = "Godown stock: " + ", ".join(f"{m.PRODUCT_LABELS[p]} {st[p]:.0f} kg" for p in m.SEEDS)
    return _form_page(request, form, "Send stock", "transfer_list", "Send", intro)


@role_required(FACTORY)
def shops(request):
    form = f.LocalShopForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Local shop added.")
        return redirect("shops")
    return render(request, "core/shops.html", {"form": form, "shops": m.LocalShop.objects.all()})


@role_required(SUPER, FACTORY)
def waste_list(request):
    return render(request, "core/waste_list.html", {
        "rows": m.WasteReturn.objects.select_related("franchise"), "form": f.WasteReceiveForm(),
        "can_receive": request.user.role == FACTORY})


@role_required(FACTORY)
def waste_receive(request, pk):
    w = get_object_or_404(m.WasteReturn, pk=pk)
    form = f.WasteReceiveForm(request.POST)
    if request.method == "POST" and form.is_valid():
        try:
            svc.receive_waste(request.user, w, form.cleaned_data["rate_per_kg"])
            messages.success(request, "Waste received and stock updated.")
        except svc.RuleError as e:
            messages.error(request, str(e))
    return redirect("waste_list")


# ---- Franchise ----------------------------------------------------------
@role_required(F_MAIN)
def confirm_transfer(request, pk):
    t = get_object_or_404(m.Transfer, pk=pk, franchise=request.user.franchise)
    form = f.ConfirmForm(t, request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            res = svc.confirm_transfer(request.user, t, form.received())
            if res.status == m.Transfer.MISMATCH:
                messages.warning(request, "Received quantity differs from what was sent. The owner has been flagged.")
            else:
                messages.success(request, "Receipt confirmed. Stock added.")
            return redirect("home")
        except svc.RuleError as e:
            form.add_error(None, str(e))
    return render(request, "core/confirm.html", {"t": t, "form": form})


@role_required(F_SUB)
def sale_new(request):
    form = f.SaleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        lines = [(p, d.get(f"qty_{p}"), d.get(f"rate_{p}")) for p in f.SaleForm.PRODUCTS]
        try:
            s = svc.create_sale(request.user, d["date"], d["customer"], lines)
            messages.success(request, f"Bill #{s.id} saved. Total ₹{s.total:,.2f}")
            return redirect("sale_list")
        except svc.RuleError as e:
            form.add_error(None, str(e))
    return render(request, "core/sale_form.html", {"form": form, "stock": stock_for(request.user.franchise)})


@role_required(F_MAIN, F_SUB)
def sale_list(request):
    rows = m.Sale.objects.filter(franchise=request.user.franchise).prefetch_related("items")[:100]
    return render(request, "core/sale_list.html", {"rows": rows})


@role_required(F_SUB)
def extraction_new(request):
    form = f.ExtractionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            svc.record_extraction(request.user, d["date"], d["seed_product"], d["seed_used"], d["oil_litres"], d["waste_kg"])
            messages.success(request, "Oil extraction recorded.")
            return redirect("extraction_list")
        except svc.RuleError as e:
            form.add_error(None, str(e))
    return _form_page(request, form, "Record oil extraction", "extraction_list", "Save")


@role_required(F_MAIN, F_SUB)
def extraction_list(request):
    return render(request, "core/extraction_list.html",
                  {"rows": m.OilExtraction.objects.filter(franchise=request.user.franchise)[:100]})


@role_required(F_SUB)
def waste_send(request):
    form = f.WasteSendForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            svc.send_waste(request.user, form.cleaned_data["date"], form.cleaned_data["qty_kg"])
            messages.success(request, "Waste marked as sent. The factory will confirm and pay.")
            return redirect("home")
        except svc.RuleError as e:
            form.add_error(None, str(e))
    st = stock_for(request.user.franchise)
    return _form_page(request, form, "Send waste to factory", "home", "Send",
                      f"Waste in stock: {st[m.WASTE]:.2f} kg")


@role_required(F_MAIN, F_SUB)
def franchise_stock(request):
    return render(request, "core/stock.html", {"fac": stock_for(request.user.franchise), "mine": True})

from django import forms
from django.utils import timezone
from . import models as m


def _date():
    return forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}))


def qty_field(label=None, required=False):
    return forms.DecimalField(label=label, required=required, min_value=0, max_digits=12,
                              decimal_places=2, widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}))


class FranchiseForm(forms.ModelForm):
    class Meta:
        model = m.Franchise
        fields = ["name", "city", "address", "contact_name", "contact_phone", "is_active"]
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}


class UserForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, min_length=6)

    class Meta:
        model = m.User
        fields = ["username", "first_name", "role", "franchise", "password"]
        labels = {"first_name": "Full name"}

    def clean(self):
        d = super().clean()
        role, fr = d.get("role"), d.get("franchise")
        if role in (m.User.F_MAIN, m.User.F_SUB) and not fr:
            self.add_error("franchise", "Choose a franchise for this role.")
        if role in (m.User.SUPER, m.User.FACTORY) and fr:
            self.add_error("franchise", "Leave franchise empty for this role.")
        return d

    def save(self, commit=True):
        u = super().save(commit=False)
        u.set_password(self.cleaned_data["password"])
        u.is_staff = u.is_superuser = (u.role == m.User.SUPER)
        if commit:
            u.save()
        return u


class LocalShopForm(forms.ModelForm):
    class Meta:
        model = m.LocalShop
        fields = ["name", "place", "phone"]


class InwardForm(forms.Form):
    date = _date()
    supplier = forms.CharField(max_length=120)
    vehicle_no = forms.CharField(max_length=30, required=False)
    total_kg = qty_field("Total load received (kg)", True)
    qty_sortex = qty_field("Sortex cleaned (kg)")
    qty_normal = qty_field("Normal cleaned (kg)")
    qty_raw = qty_field("Raw (kg)")
    notes = forms.CharField(max_length=200, required=False)


class TransferForm(forms.Form):
    date = _date()
    franchise = forms.ModelChoiceField(m.Franchise.objects.filter(is_active=True), required=False,
                                       label="To franchise")
    local_shop = forms.ModelChoiceField(m.LocalShop.objects.all(), required=False,
                                        label="Or to local shop")
    qty_sortex = qty_field("Sortex cleaned (kg)")
    qty_normal = qty_field("Normal cleaned (kg)")
    qty_raw = qty_field("Raw (kg)")
    note = forms.CharField(max_length=200, required=False)

    def clean(self):
        d = super().clean()
        if bool(d.get("franchise")) == bool(d.get("local_shop")):
            raise forms.ValidationError("Choose either a franchise or a local shop, not both.")
        return d


class SaleForm(forms.Form):
    date = _date()
    customer = forms.CharField(max_length=120, required=False, label="Customer (optional)")
    PRODUCTS = [m.SORTEX, m.NORMAL, m.RAW, m.OIL]

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        for p in self.PRODUCTS:
            self.fields[f"qty_{p}"] = qty_field(f"{m.PRODUCT_LABELS[p]} qty ({m.UNIT[p]})")
            self.fields[f"rate_{p}"] = qty_field(f"Rate per {m.UNIT[p]}")

    def clean(self):
        d = super().clean()
        for p in self.PRODUCTS:
            if d.get(f"qty_{p}") and not d.get(f"rate_{p}"):
                self.add_error(f"rate_{p}", "Enter the rate.")
        return d

    def rows(self):
        return [(p, m.PRODUCT_LABELS[p], m.UNIT[p], self[f"qty_{p}"], self[f"rate_{p}"]) for p in self.PRODUCTS]


class ExtractionForm(forms.Form):
    date = _date()
    seed_product = forms.ChoiceField(choices=[(p, m.PRODUCT_LABELS[p]) for p in m.SEEDS], label="Seed used")
    seed_used = qty_field("Seed used (kg)", True)
    oil_litres = qty_field("Oil produced (litres)", True)
    waste_kg = qty_field("Waste produced (kg)", True)


class WasteSendForm(forms.Form):
    date = _date()
    qty_kg = qty_field("Waste sent to factory (kg)", True)


class WasteReceiveForm(forms.Form):
    rate_per_kg = qty_field("Buyback rate (per kg)", True)


class ResolveForm(forms.Form):
    resolution_note = forms.CharField(max_length=200, label="Resolution note")


class ConfirmForm(forms.Form):
    def __init__(self, transfer, *a, **k):
        super().__init__(*a, **k)
        for it in transfer.items.all():
            self.fields[f"item_{it.id}"] = qty_field(f"{m.PRODUCT_LABELS[it.product]} received (kg)", True)
            self.fields[f"item_{it.id}"].initial = it.qty_sent
        self.items = list(transfer.items.all())

    def received(self):
        return {it.id: self.cleaned_data[f"item_{it.id}"] for it in self.items}

from django import template
from core import models as m

register = template.Library()


@register.filter
def plabel(p):
    return m.PRODUCT_LABELS.get(p, p)


@register.filter
def punit(p):
    return m.UNIT.get(p, "")


@register.filter
def get(d, k):
    return d.get(k)


@register.filter
def qty(v):
    if v is None:
        return "-"
    return f"{v:,.2f}".rstrip("0").rstrip(".") if v == v else v

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from . import models as m


@admin.register(m.User)
class SesameUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Sufala", {"fields": ("role", "franchise")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Sufala", {"fields": ("role", "franchise")}),)
    list_display = ("username", "first_name", "role", "franchise", "is_active")


for model in (m.Franchise, m.LocalShop, m.InwardLoad, m.Transfer, m.Sale, m.OilExtraction, m.WasteReturn, m.StockMovement):
    admin.site.register(model)

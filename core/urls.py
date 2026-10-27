from django.contrib.auth import views as auth
from django.urls import path
from . import views as v

urlpatterns = [
    path("login/", auth.LoginView.as_view(template_name="core/login.html"), name="login"),
    path("logout/", auth.LogoutView.as_view(), name="logout"),
    path("", v.home, name="home"),
    # super admin
    path("franchises/", v.franchise_list, name="franchise_list"),
    path("franchises/add/", v.franchise_edit, name="franchise_add"),
    path("franchises/<int:pk>/edit/", v.franchise_edit, name="franchise_edit"),
    path("users/", v.user_list, name="user_list"),
    path("users/add/", v.user_add, name="user_add"),
    path("reports/sales/", v.sales_report, name="sales_report"),
    path("reports/mismatches/", v.mismatches, name="mismatches"),
    path("reports/mismatches/<int:pk>/resolve/", v.resolve, name="resolve"),
    # factory
    path("stock/", v.stock_view, name="stock"),
    path("inward/", v.inward_list, name="inward_list"),
    path("inward/new/", v.inward_add, name="inward_add"),
    path("transfers/", v.transfer_list, name="transfer_list"),
    path("transfers/new/", v.transfer_new, name="transfer_new"),
    path("shops/", v.shops, name="shops"),
    path("waste/", v.waste_list, name="waste_list"),
    path("waste/<int:pk>/receive/", v.waste_receive, name="waste_receive"),
    # franchise
    path("transfers/<int:pk>/confirm/", v.confirm_transfer, name="confirm_transfer"),
    path("shop/stock/", v.franchise_stock, name="franchise_stock"),
    path("sales/new/", v.sale_new, name="sale_new"),
    path("sales/", v.sale_list, name="sale_list"),
    path("extraction/new/", v.extraction_new, name="extraction_new"),
    path("extraction/", v.extraction_list, name="extraction_list"),
    path("waste/send/", v.waste_send, name="waste_send"),
]

from decimal import Decimal as D
from django.test import TestCase
from django.urls import reverse
from . import models as m, services as svc
from .models import stock_for


class FlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f1 = m.Franchise.objects.create(name="Shop A", city="Vijayawada")
        cls.f2 = m.Franchise.objects.create(name="Shop B", city="Guntur")
        mk = lambda u, r, f=None: m.User.objects.create_user(u, password="pw12345", role=r, franchise=f)
        cls.owner = mk("owner", m.User.SUPER)
        cls.owner.is_staff = cls.owner.is_superuser = True; cls.owner.save()
        cls.fac = mk("fac", m.User.FACTORY)
        cls.main1 = mk("main1", m.User.F_MAIN, cls.f1)
        cls.sub1 = mk("sub1", m.User.F_SUB, cls.f1)
        cls.main2 = mk("main2", m.User.F_MAIN, cls.f2)

    def load(self):
        return svc.record_inward(self.fac, None or __import__("datetime").date.today(), "Farmer X", "AP1", D("1000"),
                                 "", {m.SORTEX: D("500"), m.NORMAL: D("300"), m.RAW: D("150")})

    def test_inward_adds_stock_and_wastage(self):
        l = self.load()
        st = stock_for(None)
        self.assertEqual(st[m.SORTEX], 500)
        self.assertEqual(l.wastage_kg, 50)

    def test_inward_variants_cannot_exceed_total(self):
        with self.assertRaises(svc.RuleError):
            svc.record_inward(self.fac, __import__("datetime").date.today(), "X", "", D("100"), "", {m.SORTEX: D("200")})

    def test_transfer_confirm_match(self):
        self.load()
        t = svc.create_transfer(self.fac, __import__("datetime").date.today(), self.f1, None, {m.SORTEX: D("100")})
        self.assertEqual(stock_for(None)[m.SORTEX], 400)
        self.assertEqual(stock_for(self.f1)[m.SORTEX], 0)  # in transit
        t = svc.confirm_transfer(self.main1, t, {t.items.first().id: D("100")})
        self.assertEqual(t.status, m.Transfer.CONFIRMED)
        self.assertEqual(stock_for(self.f1)[m.SORTEX], 100)

    def test_transfer_mismatch_and_resolve(self):
        self.load()
        t = svc.create_transfer(self.fac, __import__("datetime").date.today(), self.f1, None, {m.NORMAL: D("100")})
        t = svc.confirm_transfer(self.main1, t, {t.items.first().id: D("95")})
        self.assertEqual(t.status, m.Transfer.MISMATCH)
        self.assertEqual(stock_for(self.f1)[m.NORMAL], 95)
        svc.resolve_transfer(t, "spillage")
        t.refresh_from_db(); self.assertEqual(t.status, m.Transfer.RESOLVED)

    def test_other_franchise_cannot_confirm(self):
        self.load()
        t = svc.create_transfer(self.fac, __import__("datetime").date.today(), self.f1, None, {m.RAW: D("10")})
        with self.assertRaises(svc.RuleError):
            svc.confirm_transfer(self.main2, t, {t.items.first().id: D("10")})

    def test_cannot_send_more_than_stock(self):
        self.load()
        with self.assertRaises(svc.RuleError):
            svc.create_transfer(self.fac, __import__("datetime").date.today(), self.f1, None, {m.SORTEX: D("9999")})

    def test_sale_extraction_waste_cycle(self):
        self.load()
        t = svc.create_transfer(self.fac, __import__("datetime").date.today(), self.f1, None, {m.SORTEX: D("200")})
        svc.confirm_transfer(self.main1, t, {t.items.first().id: D("200")})
        today = __import__("datetime").date.today()
        s = svc.create_sale(self.sub1, today, "Ravi", [(m.SORTEX, D("10"), D("250"))])
        self.assertEqual(s.total, D("2500"))
        svc.record_extraction(self.sub1, today, m.SORTEX, D("100"), D("35"), D("60"))
        st = stock_for(self.f1)
        self.assertEqual((st[m.SORTEX], st[m.OIL], st[m.WASTE]), (D("90"), D("35"), D("60")))
        w = svc.send_waste(self.sub1, today, D("60"))
        w = svc.receive_waste(self.fac, w, D("20"))
        self.assertEqual(w.amount, D("1200"))
        self.assertEqual(stock_for(self.f1)[m.WASTE], 0)
        self.assertEqual(stock_for(None)[m.WASTE], 60)
        with self.assertRaises(svc.RuleError):
            svc.create_sale(self.sub1, today, "", [(m.SORTEX, D("500"), D("250"))])

    def test_direct_local_shop_sale(self):
        self.load()
        shop = m.LocalShop.objects.create(name="Kirana")
        t = svc.create_transfer(self.fac, __import__("datetime").date.today(), None, shop, {m.RAW: D("50")})
        self.assertEqual(t.status, m.Transfer.CONFIRMED)
        self.assertEqual(stock_for(None)[m.RAW], 100)


class AccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        FlowTests.setUpTestData.__func__(cls)

    def login(self, u):
        self.client.login(username=u, password="pw12345")

    def test_all_pages_render_per_role(self):
        pages = {
            "owner": ["home", "franchise_list", "franchise_add", "user_list", "user_add", "sales_report", "mismatches", "inward_list", "transfer_list", "waste_list"],
            "fac": ["home", "inward_list", "inward_add", "stock", "transfer_list", "transfer_new", "shops", "waste_list"],
            "main1": ["home", "transfer_list", "sale_list", "franchise_stock", "extraction_list"],
            "sub1": ["home", "sale_new", "sale_list", "extraction_new", "extraction_list", "waste_send", "franchise_stock"],
        }
        for u, names in pages.items():
            self.login(u)
            for n in names:
                r = self.client.get(reverse(n))
                self.assertEqual(r.status_code, 200, f"{u} {n}")
            self.client.logout()

    def test_role_blocking(self):
        self.login("sub1")
        for n in ["franchise_list", "inward_add", "transfer_new", "user_list", "sales_report"]:
            self.assertEqual(self.client.get(reverse(n)).status_code, 403, n)
        self.client.logout(); self.login("main1")
        self.assertEqual(self.client.get(reverse("sale_new")).status_code, 403)
        self.client.logout(); self.login("fac")
        self.assertEqual(self.client.get(reverse("sale_new")).status_code, 403)

    def test_anonymous_redirected(self):
        self.assertEqual(self.client.get(reverse("home")).status_code, 302)

    def test_franchise_isolation_in_views(self):
        d = __import__("datetime").date.today()
        fac = m.User.objects.get(username="fac")
        svc.record_inward(fac, d, "X", "", D("100"), "", {m.SORTEX: D("100")})
        svc.create_transfer(fac, d, self.f1, None, {m.SORTEX: D("50")})
        self.login("main2")
        r = self.client.get(reverse("transfer_list"))
        self.assertEqual(len(r.context["rows"]), 0)
        t = m.Transfer.objects.first()
        self.assertEqual(self.client.get(reverse("confirm_transfer", args=[t.id])).status_code, 404)

    def test_post_flow_through_views(self):
        d = __import__("datetime").date.today().isoformat()
        self.login("fac")
        r = self.client.post(reverse("inward_add"), {"date": d, "supplier": "Farmer", "total_kg": "1000", "qty_sortex": "600", "qty_normal": "300", "qty_raw": "0"})
        self.assertEqual(r.status_code, 302)
        r = self.client.post(reverse("transfer_new"), {"date": d, "franchise": self.f1.id, "qty_sortex": "100"})
        self.assertEqual(r.status_code, 302)
        self.client.logout(); self.login("main1")
        t = m.Transfer.objects.get()
        item = t.items.first()
        r = self.client.post(reverse("confirm_transfer", args=[t.id]), {f"item_{item.id}": "100"})
        self.assertEqual(r.status_code, 302)
        self.client.logout(); self.login("sub1")
        r = self.client.post(reverse("sale_new"), {"date": d, "customer": "A", "qty_sortex": "5", "rate_sortex": "300"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(m.Sale.objects.get().total, D("1500"))
        self.client.logout(); self.login("owner")
        r = self.client.get(reverse("home"))
        self.assertContains(r, "Shop A")
        r = self.client.get(reverse("sales_report"))
        self.assertContains(r, "1,500")

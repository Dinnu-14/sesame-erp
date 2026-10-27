from django.core.management.base import BaseCommand
from core import models as m, services as svc


class Command(BaseCommand):
    help = "Create demo franchise and login accounts (safe to run more than once)."

    def handle(self, *a, **k):
        fr, _ = m.Franchise.objects.get_or_create(name="Sufala Vijayawada", defaults={"city": "Vijayawada"})
        users = [("owner", "Owner", m.User.SUPER, None), ("factory", "Factory Operator", m.User.FACTORY, None),
                 ("shopmain", "Shop Manager", m.User.F_MAIN, fr), ("shopstaff", "Shop Staff", m.User.F_SUB, fr)]
        for uname, name, role, franchise in users:
            u, created = m.User.objects.get_or_create(username=uname, defaults={
                "first_name": name, "role": role, "franchise": franchise,
                "is_staff": role == m.User.SUPER, "is_superuser": role == m.User.SUPER})
            if created:
                u.set_password("sufala123")
                u.save()
        self.stdout.write("Demo users ready: owner, factory, shopmain, shopstaff (password: sufala123)")

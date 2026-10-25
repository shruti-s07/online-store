"""Seed the database from the synthetic world (ai/generators.py).

Sizes and random seed come from config/ml.yaml; demo account credentials from .env.
"""
from __future__ import annotations

import time
from datetime import timedelta

import numpy as np
from django.contrib.auth.hashers import make_password
from django.core.files.base import ContentFile
from django.core.management import BaseCommand, CommandError, call_command
from django.db import connection, transaction
from django.utils import timezone

from ai.generators import generate_world
from ai.images import product_image, to_png_bytes
from backend.folder_one_core.accounts.models import Address, User
from backend.folder_one_core.catalog.models import Category, Product, ProductImage
from backend.folder_one_core.inventory.models import Inventory, StockMovement
from backend.folder_one_core.orders.models import Order, OrderItem, OrderStatusHistory
from backend.folder_one_core.payments.models import Payment
from backend.shared.hooks import import_dotted
from backend.shared.payment_methods import cod_method, is_prepaid
from backend.shared.order_states import SYSTEM, OrderStatus, can_transition
from backend.shared.roles import Role
from config import loader

S = OrderStatus
# Status path to each final state (all transitions are validated against the state table)
PATHS = {
    "DELIVERED": ["PROCESSING", "SHIPPED", "DELIVERED"],
    "RETURNED": ["PROCESSING", "SHIPPED", "DELIVERED", "RETURN_REQUESTED", "RETURNED", "REFUNDED"],
    "CANCELLED": ["CANCELLED"],
    "DELIVERY_REFUSED": ["PROCESSING", "SHIPPED", "DELIVERY_REFUSED"],
    "REFUNDED": ["PROCESSING", "SHIPPED", "DELIVERED"],  # prepaid fraud: delivered, then charged back
    "PAID": [], "CONFIRMED": [],
    "PROCESSING": ["PROCESSING"], "SHIPPED": ["PROCESSING", "SHIPPED"],
}


class Command(BaseCommand):
    help = "Seed the store with a reproducible synthetic history (config/ml.yaml)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete ALL existing data first")
        parser.add_argument("--scale", type=float, default=1.0, help="Shrink the world (tests)")
        parser.add_argument("--skip-extensions", action="store_true")

    def handle(self, *args, reset=False, scale=1.0, skip_extensions=False, **opts):
        if User.objects.exists() and not reset:
            raise CommandError("Database already has data. Re-run with --reset to wipe and reseed.")
        if reset:
            call_command("flush", interactive=False, verbosity=0)
            self._clear_media()
        t0 = time.time()
        today = timezone.now().date()
        world = generate_world(today, scale=scale)
        self.stdout.write(f"Generated world: {len(world.products)} products, {len(world.customers)} customers, "
                          f"{len(world.orders)} orders ({time.time() - t0:.1f}s)")
        self._write_ground_truth(world)
        with transaction.atomic():
            ctx = self._seed_core(world, today)
            for path in ([] if skip_extensions else loader.business()["seed"]["extensions"]):
                import_dotted(path)(world, ctx)
        # Fresh planner statistics after bulk loading (otherwise the first queries get bad plans)
        with connection.cursor() as cur:
            cur.execute("ANALYZE")
        self.stdout.write(self.style.SUCCESS(f"Seed complete in {time.time() - t0:.1f}s"))

    def _clear_media(self) -> None:
        """Uploaded files belong to the rows that flush just deleted; remove them so reseeding
        doesn't leave orphaned images behind."""
        import shutil
        from pathlib import Path

        from django.conf import settings
        root = Path(settings.MEDIA_ROOT)
        for sub in ("products", "snapcheck"):
            if (root / sub).is_dir():
                shutil.rmtree(root / sub)

    def _write_ground_truth(self, world) -> None:
        """Hidden generator truth, used ONLY to evaluate models (ai/models/REPORT.md)."""
        from ai import common
        out = common.DATA_DIR
        out.mkdir(parents=True, exist_ok=True)
        cust = world.customers.copy()
        demo_idx = int(cust.index[cust["segment"] == "loyal"][0])
        cust.loc[demo_idx, "email"] = loader.env("SEED_CUSTOMER_EMAIL")
        cust[["email", "segment", "fraudster"]].to_csv(out / "truth_customers.csv", index=False)
        fake = world.reviews[world.reviews["fake"]]
        fake.assign(sku=[world.products.iloc[int(p)].sku for p in fake["product"]])[["fake_email", "sku"]].to_csv(
            out / "truth_fake_reviews.csv", index=False)
        world.promotions[["category_slug", "start", "end", "discount", "true_elasticity"]].to_csv(
            out / "truth_promotions.csv", index=False)

    # ------------------------------------------------------------------ core
    def _seed_core(self, world, today) -> dict:
        rng = np.random.default_rng(loader.ml()["random_seed"])
        size = loader.ml()["synthetic"]["image_size"]
        cats = {}
        for c in loader.categories():
            cats[c["slug"]] = Category.objects.create(name=c["name"], slug=c["slug"])

        created = timezone.now() - timedelta(days=loader.ml()["synthetic"]["history_days"] + 1)
        products = Product.objects.bulk_create([
            Product(sku=p.sku, name=p.name, description=p.description, brand=p.brand,
                    category=cats[p.category_slug], price=p.price, cost=p.cost,
                    supplier_lead_time_days=p.lead_time, created_at=created,
                    attributes={"type": p.noun})
            for p in world.products.itertuples()])
        for p, row in zip(products, world.products.itertuples()):
            img = ProductImage(product=p, is_primary=True, alt_text=p.name)
            img.image.save("main.png", ContentFile(to_png_bytes(product_image(row.icon, row.color_seed, size))),
                           save=False)
            img.save()
        Inventory.objects.bulk_create([Inventory(product=p, on_hand=int(q)) for p, q in zip(products, world.stock)])
        StockMovement.objects.bulk_create([StockMovement(product=p, delta=int(q), reason="INITIAL", reference="seed")
                                           for p, q in zip(products, world.stock)])
        self.stdout.write(f"  products + images: {len(products)}")

        # Users. One Argon2 hash is computed per password and reused (same password).
        env = loader.env
        staff_users = [
            User(email=env("SEED_ADMIN_EMAIL"), password=make_password(env("SEED_ADMIN_PASSWORD")),
                 role=Role.ADMIN.value, first_name="Ada", last_name="Admin", is_staff=True,
                 date_joined=created),
            User(email=env("SEED_STAFF_EMAIL"), password=make_password(env("SEED_STAFF_PASSWORD")),
                 role=Role.STAFF.value, first_name="Sam", last_name="Staff", date_joined=created),
        ]
        User.objects.bulk_create(staff_users)
        cust_hash = make_password(env("SEED_CUSTOMER_PASSWORD"))
        cust = world.customers
        demo_idx = int(cust.index[cust["segment"] == "loyal"][0])
        users = []
        for i, c in enumerate(cust.itertuples()):
            email = env("SEED_CUSTOMER_EMAIL") if i == demo_idx else c.email
            joined = timezone.make_aware(timezone.datetime.combine(c.joined, timezone.datetime.min.time()))
            users.append(User(email=email, password=cust_hash, role=Role.CUSTOMER.value, first_name=c.first_name,
                              last_name=c.last_name, phone=c.phone, date_joined=joined))
        users = User.objects.bulk_create(users)
        addrs = []
        places = loader.india()
        for u, c in zip(users, cust.itertuples()):
            addrs.append(Address(user=u, label="Home", full_name=f"{c.first_name} {c.last_name}", line1=c.street,
                                 line2=c.street2, city=c.city, state=c.state, postal_code=c.postal,
                                 country=places["country"], phone=c.phone,
                                 is_default=True))
            addrs.append(Address(user=u, label="Other", full_name=f"{c.first_name} {c.last_name}",
                                 line1=c.alt_street, line2=c.alt_street2, city=c.alt_city, state=c.alt_state,
                                 postal_code=c.alt_postal, country=places["country"], phone=c.phone,
                                 is_default=False))
        addrs = Address.objects.bulk_create(addrs)
        home = {users[i].id: addrs[2 * i].snapshot() for i in range(len(users))}
        other = {users[i].id: addrs[2 * i + 1].snapshot() for i in range(len(users))}
        self.stdout.write(f"  users: {len(users) + 2} (demo customer = generated customer #{demo_idx})")

        # Orders
        seed_cfg = loader.business()["seed"]
        mix = seed_cfg["prepaid_mix"]
        mix_methods, mix_p = list(mix), np.array(list(mix.values()), dtype=float)
        step_days = seed_cfg["status_step_days"]
        orders = []
        for o in world.orders.itertuples():
            uid = users[o.customer].id
            method = cod_method() if o.cod else str(rng.choice(mix_methods, p=mix_p / mix_p.sum()))
            final = {"REFUNDED": "DELIVERED", "RETURNED": "REFUNDED"}.get(o.status, o.status)
            orders.append(Order(
                user_id=uid, status=final, payment_method=method, subtotal=o.total, total=o.total,
                shipping_address=home[uid] if o.address_match else other[uid], billing_address=home[uid],
                address_match=o.address_match, created_at=o.created_at, fraud_confirmed=o.fraud))
        orders = Order.objects.bulk_create(orders, batch_size=2000)
        items = world.items
        oitems = OrderItem.objects.bulk_create([
            OrderItem(order=orders[it.order], product=products[it.product], sku=products[it.product].sku,
                      name=products[it.product].name, unit_price=it.unit_price, unit_cost=it.unit_cost,
                      quantity=it.qty, line_total=round(it.unit_price * it.qty, 2))
            for it in items.itertuples()], batch_size=5000)
        item_ids = {(int(it.order), int(it.product)): oi.id for it, oi in zip(items.itertuples(), oitems)}

        history, payments = [], []
        for o, w in zip(orders, world.orders.itertuples()):
            prepaid = is_prepaid(o.payment_method)
            first = "PAID" if prepaid else "CONFIRMED"
            path = [first] + PATHS[w.status]
            prev, t = "", o.created_at
            history.append(OrderStatusHistory(order=o, from_status="", to_status="PENDING", actor_label="CUSTOMER",
                                              note="Order placed", created_at=t))
            prev = "PENDING"
            for st in path:
                actor = SYSTEM if st in ("PAID", "CONFIRMED") else (
                    Role.CUSTOMER if st == "RETURN_REQUESTED" else Role.STAFF)
                if st == "CANCELLED":
                    actor = Role.CUSTOMER
                assert can_transition(prev, st, actor), (prev, st, actor)
                t = o.created_at + timedelta(days=step_days[st])
                history.append(OrderStatusHistory(order=o, from_status=prev, to_status=st, actor_label=str(actor),
                                                  created_at=t))
                prev = st
            assert prev == o.status, (prev, o.status)
            refunded = o.status in ("REFUNDED", "CANCELLED")
            if prepaid:
                payments.append(Payment(order=o, user_id=o.user_id, idempotency_key=f"seed-{o.id}", method=o.payment_method,
                                        amount=o.total, status="REFUNDED" if refunded else "SUCCEEDED",
                                        gateway_ref=f"ch_seed_{o.id}", request_fingerprint="seed", message="seed"))
            elif o.status in ("DELIVERED", "RETURN_REQUESTED", "RETURNED", "REFUNDED"):
                payments.append(Payment(order=o, user_id=o.user_id, idempotency_key=f"cod-{o.id}", method=cod_method(),
                                        amount=o.total, status="REFUNDED" if refunded else "SUCCEEDED",
                                        gateway_ref=f"cod_{o.id}", request_fingerprint="seed",
                                        message="Cash collected on delivery"))
        OrderStatusHistory.objects.bulk_create(history, batch_size=10000)
        Payment.objects.bulk_create(payments, batch_size=5000)
        self.stdout.write(f"  orders: {len(orders)}, items: {len(oitems)}, history rows: {len(history)}")
        return {"today": today, "products": products, "users": users, "orders": orders, "item_ids": item_ids,
                "categories": cats, "customer_hash": cust_hash}

"""Folder two's seed extension (registered in config/business.yaml seed.extensions)."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from backend.folder_one_core.accounts.models import User
from backend.folder_one_core.orders.models import Order
from backend.folder_one_core.orders.services import build_risk_snapshot
from backend.shared import hooks
from backend.shared.order_states import TERMINAL_STATES
from backend.shared.roles import Role
from config.loader import business

from .discounts.models import DiscountRule, PastPromotion
from .reviews import intelligence
from .reviews.models import Review


def seed_services(world, ctx) -> None:
    cats = ctx["categories"]
    PastPromotion.objects.bulk_create([
        PastPromotion(name=p.name, category=cats[p.category_slug], discount_pct=round(p.discount, 4),
                      starts_on=p.start, ends_on=p.end) for p in world.promotions.itertuples()])
    for r in business()["discounts"]["seed_rules"]:
        DiscountRule.objects.create(name=r["name"], code=r["code"], conditions=r["conditions"], action=r["action"],
                                    status=DiscountRule.Status.APPROVED, source=DiscountRule.Source.MANUAL,
                                    decided_at=timezone.now())

    products, users, item_ids = ctx["products"], ctx["users"], ctx["item_ids"]
    fake_users = {}
    reviews = []
    for r in world.reviews.itertuples():
        if r.fake:
            u = fake_users.get(r.fake_email) or User(
                email=r.fake_email, password=ctx["customer_hash"], role=Role.CUSTOMER.value, first_name="",
                last_name="", date_joined=r.created_at - timedelta(days=1))
            fake_users[r.fake_email] = u
            reviews.append((u, r, None))
        else:
            reviews.append((users[int(r.customer)], r, item_ids.get((int(r.order), int(r.product)))))
    User.objects.bulk_create(list(fake_users.values()))
    Review.objects.bulk_create([
        Review(product=products[int(r.product)], user=u, order_item_id=item, rating=int(r.rating), title=r.title,
               body=r.body, verified_purchase=item is not None, created_at=r.created_at)
        for u, r, item in reviews], batch_size=2000, ignore_conflicts=True)
    n = intelligence.analyse_all()
    print(f"  promotions: {len(world.promotions)}, reviews: {n} (analysed), fake accounts: {len(fake_users)}")

    # Score still-open orders with the configured risk hook (rules until the model is trained)
    open_orders = Order.objects.exclude(status__in=[s.value for s in TERMINAL_STATES] + ["DELIVERED"])
    for o in open_orders.select_related("user").prefetch_related("items"):
        risk = hooks.score_order(build_risk_snapshot(o))
        o.risk_score, o.risk_level, o.risk_reasons, o.risk_model = risk.score, risk.level, list(risk.reasons), risk.model
        o.save(update_fields=["risk_score", "risk_level", "risk_reasons", "risk_model"])
    print(f"  risk-scored open orders: {open_orders.count()}")

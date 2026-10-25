"""100 simultaneous buyers compete for 10 units: exactly 10 orders must be created."""
import threading

import pytest
from django.db import connection, connections

from backend.folder_one_core.cart.services import set_quantity
from backend.folder_one_core.inventory.models import Inventory
from backend.folder_one_core.orders.models import Order
from backend.folder_one_core.orders.services import checkout
from backend.shared.errors import OutOfStock
from tests.conftest import make_address, make_product, make_user

BUYERS, UNITS = 100, 10


@pytest.mark.django_db(transaction=True)
def test_hundred_buyers_ten_units(stub_hooks):
    with connection.cursor() as cur:
        cur.execute("SHOW max_connections")
        assert int(cur.fetchone()[0]) > BUYERS + 5, "PostgreSQL max_connections must exceed 105 (see README)"
    product = make_product(stock=UNITS)
    buyers = []
    for _ in range(BUYERS):
        u = make_user()
        make_address(u)
        set_quantity(u, product.id, 1)  # all carts filled while stock is still there
        buyers.append(u)

    barrier = threading.Barrier(BUYERS)
    results, errors = [], []
    lock = threading.Lock()

    def buy(user):
        try:
            barrier.wait()
            order, _ = checkout(user, shipping_address_id=user.addresses.first().id, billing_address_id=None,
                                payment_method="CARD", payment_token="tok_visa", idempotency_key=f"c-{user.id}")
            with lock:
                results.append(order.status)
        except OutOfStock:
            with lock:
                results.append("OUT_OF_STOCK")
        except Exception as exc:  # pragma: no cover - surfaced by the assertion below
            with lock:
                errors.append(repr(exc))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=buy, args=(u,)) for u in buyers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert results.count("PAID") == UNITS
    assert results.count("OUT_OF_STOCK") == BUYERS - UNITS
    assert Order.objects.count() == UNITS
    assert Inventory.objects.get(product=product).on_hand == 0

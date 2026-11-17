# legacy/checkout.py
import json
from datetime import datetime

import requests

orders = []
last_id = 0


def checkout(data):
    global last_id

    if not data.get("items") or len(data["items"]) == 0:
        return {"ok": False, "msg": "no items"}
    if not data.get("email") or "@" not in data["email"]:
        return {"ok": False, "msg": "bad email"}

    total = 0
    for it in data["items"]:
        if it["qty"] <= 0:
            return {"ok": False, "msg": "bad qty"}
        total = total + it["price"] * it["qty"]

    # discounts
    if data.get("promo") == "SALE10":
        total = total - total * 0.1
    elif data.get("promo") == "MINUS50":
        if total > 500:
            total = total - 50
    elif data.get("promo") == "FREESHIP":
        data["free_ship"] = True
    if data.get("user_type") == "vip":
        total = total * 0.95

    # shipping
    ship = 0
    if not data.get("free_ship"):
        if data.get("delivery") == "nova":
            ship = 0 if total > 1000 else 70
        elif data.get("delivery") == "ukr":
            ship = 45
        elif data.get("delivery") == "courier":
            ship = 120
            if data.get("city") != "Kyiv":
                ship = ship + 50
        else:
            return {"ok": False, "msg": "bad delivery"}
    total = total + ship

    # payment
    paid = False
    if data.get("payment") == "card":
        r = requests.post(
            "https://payments.example.com/charge",
            json={"amount": total, "card": data.get("card")},
        )
        if r.json()["status"] == "ok":
            paid = True
        else:
            return {"ok": False, "msg": "payment failed"}
    elif data.get("payment") == "cod":
        if total > 5000:
            return {"ok": False, "msg": "cod limit"}
    elif data.get("payment") == "invoice":
        if data.get("user_type") != "b2b":
            return {"ok": False, "msg": "invoice only b2b"}

    last_id += 1
    order = {
        "id": last_id,
        "email": data["email"],
        "items": data["items"],
        "total": total,
        "status": "paid" if paid else "new",
        "created": datetime.now(),
    }
    orders.append(order)

    with open("orders.log", "a") as f:
        f.write(json.dumps(order, default=str) + "\n")
    print("order created", order["id"])

    # notify
    if data.get("user_type") == "vip":
        requests.post(
            "https://mail.example.com/send",
            json={"to": data["email"], "template": "vip_order", "total": total},
        )
    else:
        requests.post(
            "https://mail.example.com/send",
            json={"to": data["email"], "template": "order", "total": total},
        )
    if total > 10000:
        requests.post(
            "https://slack.example.com/hook",
            json={"text": "Big order " + str(order["id"])},
        )

    return {"ok": True, "order": order}


def change_status(order_id, status):
    for o in orders:
        if o["id"] == order_id:
            o["status"] = status
            return True
    return False

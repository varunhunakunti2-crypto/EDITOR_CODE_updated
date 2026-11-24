"""Browser checks + screenshot generator.

Run from the project folder while the server is up:
    python tests/browser_check.py

Requires Playwright with Chromium installed. Temporary demo accounts, products
and a design are created for the screenshots, then removed again. Screenshots
are written to docs/screenshots/.
"""
import json
import os
import sqlite3
import time
import uuid

from playwright.sync_api import sync_playwright

from smoke_test import BASE, DB, multipart, openers, post, request

SHOTS = os.path.join("docs", "screenshots")
os.makedirs(SHOTS, exist_ok=True)

PASS, FAIL = [], []


def check(label, ok, detail=""):
    (PASS if ok else FAIL).append(label)
    print(("PASS " if ok else "FAIL ") + label + ((" | " + str(detail)) if detail else ""), flush=True)


def shot(page, name):
    path = os.path.join(SHOTS, name + ".png")
    page.screenshot(path=path, full_page=True)
    print("  screenshot:", path, flush=True)


def register(role, prefix):
    follow, strict = openers()
    username = prefix + uuid.uuid4().hex[:6]
    post(follow, "/register", {"username": username, "email": username + "@t.local",
                               "password": "pass123", "role": role})
    post(strict, "/login", {"username": username, "password": "pass123"})
    return follow, strict, username


def login(page, username):
    page.goto(BASE + "/login", timeout=30000)
    page.fill("#username", username)
    page.fill("#password", "pass123")
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")


def setup_demo():
    admin_f, admin_s, admin_u = register("customer", "shot_admin_")
    shop_f, shop_s, shop_u = register("shop_owner", "shot_shop_")
    cust_f, cust_s, cust_u = register("customer", "shot_cust_")
    with sqlite3.connect(DB) as con:
        admin_id = con.execute("SELECT id FROM user WHERE username=?", (admin_u,)).fetchone()[0]
        shop_id = con.execute("SELECT id FROM user WHERE username=?", (shop_u,)).fetchone()[0]
        cust_id = con.execute("SELECT id FROM user WHERE username=?", (cust_u,)).fetchone()[0]
        con.execute("UPDATE user SET role='admin' WHERE id=?", (admin_id,))
    post(admin_s, "/login", {"username": admin_u, "password": "pass123"})
    post(shop_f, "/shop/profile", {"shop_name": "Demo Interiors", "city": "Bengaluru",
                                   "address": "1 Demo Street", "phone": "9876543210"})
    post(admin_s, f"/admin/shops/{shop_id}/verify", {"verified": "1"})

    products, images = [], []
    for name, category, price, filename in [
        ("Oak Bookshelf", "Shelving", "8999", "sample.jpg"),
        ("Linen Accent Chair", "Seating", "14500", "test.jpg"),
        ("Brass Floor Lamp", "Lighting", "4599", "edited_room.png"),
    ]:
        image = open(filename, "rb").read()
        ext = os.path.splitext(filename)[1]
        body, ctype = multipart({"name": name, "category": category, "price": price,
                                 "dimensions": "90 x 30 x 120 cm",
                                 "description": "Hand-finished and made to last."},
                                "item" + ext, image)
        request(shop_f, "/shop/products/add", body, ctype)
    with sqlite3.connect(DB) as con:
        products = con.execute("SELECT id, name, image_file FROM product WHERE owner_id=?",
                               (shop_id,)).fetchall()
        images = [p[2] for p in products]
        places = {
            "item": "wooden bookshelf", "location": "Koramangala, Bengaluru",
            "places": [{"name": "Home Centre", "type": "Furniture store",
                        "area": "Koramangala", "why": "Known for wooden shelving",
                        "map_url": "https://www.google.com/maps/search/?api=1&query=Home+Centre"}],
            "search_url": "https://www.google.com/maps/search/?api=1&query=furniture+Koramangala",
        }
        design_id = con.execute(
            "INSERT INTO design (user_id,input_image,mask_image,output_image,prompt,position,location,places_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (cust_id, "61764adc-42b9-4ec0-bbe3-5ee6358d8a05.jpg",
             "mask_61764adc-42b9-4ec0-bbe3-5ee6358d8a05.jpg",
             "output_61764adc-42b9-4ec0-bbe3-5ee6358d8a05.jpg",
             "add a wooden bookshelf on the wall", "middle_center",
             "Koramangala, Bengaluru", json.dumps(places)),
        ).lastrowid
    return dict(admin=admin_u, shop=shop_u, cust=cust_u, shop_id=shop_id,
                products=products, images=images, design_id=design_id)


def cleanup(demo):
    with sqlite3.connect(DB) as con:
        ids = [con.execute("SELECT id FROM user WHERE username=?", (demo[k],)).fetchone()[0]
               for k in ("admin", "shop", "cust")]
        marks = ",".join("?" * len(ids))
        con.execute("DELETE FROM enquiry WHERE customer_id IN (%s) "
                    "OR shop_owner_id IN (%s)" % (marks, marks), ids + ids)
        con.execute("DELETE FROM shop_profile WHERE owner_id IN (%s)" % marks, ids)
        con.execute("DELETE FROM product WHERE owner_id IN (%s)" % marks, ids)
        con.execute("DELETE FROM design WHERE id=?", (demo["design_id"],))
        con.execute("DELETE FROM user WHERE id IN (%s)" % marks, ids)
    for name in demo["images"]:
        try:
            os.remove(os.path.join("static", "uploads", "products", name))
        except OSError:
            pass


def main():
    for _ in range(40):
        try:
            request(openers()[0], "/model-status")
            break
        except Exception:
            time.sleep(1)

    demo = setup_demo()
    errors, bad = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("response", lambda r: bad.append((r.status, r.url)) if r.status >= 400 else None)

            # Public pages
            page.goto(BASE + "/")
            page.wait_for_load_state("networkidle")
            shot(page, "01-home")
            page.goto(BASE + "/register")
            shot(page, "02-register")
            check("home + register render", page.locator("h1").count() >= 1)

            # Shop owner
            login(page, demo["shop"])
            check("shop owner lands on /shop", page.url.endswith("/shop"), page.url)
            page.wait_for_load_state("networkidle")
            shot(page, "03-shop-dashboard")
            page.goto(BASE + "/shop/products")
            page.wait_for_load_state("networkidle")
            shot(page, "04-product-list")
            check("product cards render", page.locator(".product-card").count() == 3)
            page.goto(BASE + "/shop/products/add")
            shot(page, "05-add-product")
            check("add form has image field", page.locator("input[type=file][name=image]").count() == 1)

            # Catalogue + details
            page.goto(BASE + "/products")
            page.wait_for_load_state("networkidle")
            shot(page, "06-catalogue")
            detail_url = BASE + "/products/" + str(demo["products"][0][0])
            page.goto(detail_url)
            page.wait_for_selector(".detail-grid")
            page.wait_for_load_state("networkidle")
            shot(page, "07-product-detail")
            check("detail image loaded",
                  page.locator(".detail-media img").evaluate("i => i.complete && i.naturalWidth > 0"))

            # Customer result page + drag-drop placement
            login(page, demo["cust"])
            page.goto(BASE + "/design/" + str(demo["design_id"]))
            page.wait_for_selector("[data-placement]")
            page.wait_for_load_state("networkidle")
            canvas = page.locator("[data-canvas]")
            palette = page.locator(".palette-item[data-src]").first
            canvas.scroll_into_view_if_needed()
            cb, sb = canvas.bounding_box(), palette.bounding_box()
            page.mouse.move(sb["x"] + sb["width"] / 2, sb["y"] + sb["height"] / 2)
            page.mouse.down()
            page.mouse.move(cb["x"] + cb["width"] * 0.66, cb["y"] + cb["height"] * 0.58, steps=20)
            page.mouse.up()
            page.wait_for_selector(".placed-item", timeout=5000)
            check("browser drag places item", page.locator(".placed-item").count() == 1)
            shot(page, "08-result-placement")

            # Customer dashboard
            page.goto(BASE + "/dashboard")
            page.wait_for_load_state("networkidle")
            shot(page, "09-customer-dashboard")

            # Admin pages
            login(page, demo["admin"])
            for path, name, marker in [
                ("/admin", "10-admin-dashboard", "Admin dashboard"),
                ("/admin/users", "11-admin-users", "All accounts"),
                ("/admin/shops", "12-admin-shops", "Shop owners"),
                ("/admin/shops/" + str(demo["shop_id"]), "13-admin-shop", "catalogue"),
            ]:
                page.goto(BASE + path)
                page.wait_for_load_state("networkidle")
                shot(page, name)
                check("admin page " + path, marker in page.content())

            check("no browser errors", not errors, errors[:3])
            check("no failed resources", not bad, bad[:3])
            browser.close()
    finally:
        cleanup(demo)

    print("\nSUMMARY:", len(PASS), "passed,", len(FAIL), "failed")
    if FAIL:
        print("FAILED:", FAIL)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

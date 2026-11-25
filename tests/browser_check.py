"""Browser checks + screenshot generator.

Run from the project folder while the server is up:
    python tests/browser_check.py

Requires Playwright with Chromium installed. Temporary demo accounts for all
four roles, products and one design per role are created for the screenshots and
the six-step PDF walkthrough, then removed again. Screenshots are written to
docs/screenshots/.
"""
import base64
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
    designer_f, designer_s, designer_u = register("customer", "shot_designer_")
    with sqlite3.connect(DB) as con:
        admin_id = con.execute("SELECT id FROM user WHERE username=?", (admin_u,)).fetchone()[0]
        shop_id = con.execute("SELECT id FROM user WHERE username=?", (shop_u,)).fetchone()[0]
        cust_id = con.execute("SELECT id FROM user WHERE username=?", (cust_u,)).fetchone()[0]
        designer_id = con.execute("SELECT id FROM user WHERE username=?", (designer_u,)).fetchone()[0]
        con.execute("UPDATE user SET role='admin' WHERE id=?", (admin_id,))
        con.execute("UPDATE user SET role='designer' WHERE id=?", (designer_id,))
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
        con.execute(
            "INSERT INTO enquiry (product_id, customer_id, shop_owner_id, message, kind, status) "
            "VALUES (?,?,?,?,?,?)",
            (products[0][0], cust_id, shop_id,
             "Could you share the dimensions?", "enquiry", "responded"),
        )
        places = {
            "item": "wooden bookshelf", "location": "Koramangala, Bengaluru",
            "places": [{"name": "Home Centre", "type": "Furniture store",
                        "area": "Koramangala", "why": "Known for wooden shelving",
                        "map_url": "https://www.google.com/maps/search/?api=1&query=Home+Centre"}],
            "search_url": "https://www.google.com/maps/search/?api=1&query=furniture+Koramangala",
        }
        # One design per role so the PDF step-by-step walkthrough can open a
        # real result page as each of the four users.
        designs = {}
        for role, owner_id in [("customer", cust_id), ("designer", designer_id),
                               ("shop_owner", shop_id), ("admin", admin_id)]:
            designs[role] = con.execute(
                "INSERT INTO design (user_id,input_image,mask_image,output_image,prompt,"
                "position,location,places_json,room_type,style,budget,width_m,length_m,height_m) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (owner_id, "61764adc-42b9-4ec0-bbe3-5ee6358d8a05.jpg",
                 "mask_61764adc-42b9-4ec0-bbe3-5ee6358d8a05.jpg",
                 "output_61764adc-42b9-4ec0-bbe3-5ee6358d8a05.jpg",
                 "add a wooden bookshelf on the wall", "middle_center",
                 "Koramangala, Bengaluru", json.dumps(places),
                 "living_room", "modern", "50000 INR", 4.5, 5.0, 2.7),
            ).lastrowid
    return dict(admin=admin_u, shop=shop_u, cust=cust_u, designer=designer_u,
                shop_id=shop_id, products=products, images=images,
                design_id=designs["customer"], designs=designs)


def cleanup(demo):
    with sqlite3.connect(DB) as con:
        ids = [con.execute("SELECT id FROM user WHERE username=?", (demo[k],)).fetchone()[0]
               for k in ("admin", "shop", "cust", "designer")]
        marks = ",".join("?" * len(ids))
        con.execute("DELETE FROM enquiry WHERE customer_id IN (%s) "
                    "OR shop_owner_id IN (%s)" % (marks, marks), ids + ids)
        con.execute("DELETE FROM shop_profile WHERE owner_id IN (%s)" % marks, ids)
        con.execute("DELETE FROM product WHERE owner_id IN (%s)" % marks, ids)
        con.execute("DELETE FROM design WHERE user_id IN (%s)" % marks, ids)
        con.execute("DELETE FROM user WHERE id IN (%s)" % marks, ids)
    for name in demo["images"]:
        try:
            os.remove(os.path.join("static", "uploads", "products", name))
        except OSError:
            pass


def analyze_in_browser(page):
    """POST /api/analyze-room using the browser, like the design form does."""
    encoded = base64.b64encode(open("sample.jpg", "rb").read()).decode()
    return page.evaluate("""async (data) => {
        const raw = atob(data);
        const bytes = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
        const form = new FormData();
        form.append('image', new File([bytes], 'room.jpg', {type: 'image/jpeg'}));
        form.append('reference_pixels', '180');
        const res = await fetch('/api/analyze-room', {method: 'POST', body: form});
        return {status: res.status, data: await res.json()};
    }""", encoded)


ROLE_LANDING = {
    "admin": "/admin", "customer": "/dashboard",
    "designer": "/dashboard", "shop_owner": "/shop",
}
ROLE_WALK_SHOT = {
    "admin": "24-admin-walkthrough",
    "designer": "25-designer-walkthrough",
    "shop_owner": "26-shop-owner-walkthrough",
}


def pdf_walkthrough(page, demo, role, username, capture=False):
    """Walk the six numbered steps from the project PDF as one role."""
    tag = "PDF step " + role

    # Step 1 — user login (all four roles).
    login(page, username)
    check(tag + " 1 login", page.url.endswith(ROLE_LANDING[role]), page.url)
    if capture:
        shot(page, "18-step1-login")

    # Step 2 — upload a room image (the design form is open to every role).
    page.goto(BASE + "/design")
    page.wait_for_load_state("networkidle")
    check(tag + " 2 upload form", page.locator("input[type=file][name=image]").count() == 1
          and page.locator("#prompt").count() == 1)
    if role == "customer":
        check(tag + " 2 default preset",
              page.locator('input[name=position][value=middle_center]').is_checked())
        check(tag + " 2 custom option",
              page.locator('input[name=position][value=custom]').count() == 1)
        page.set_input_files('input[name=image]', 'sample.jpg')
        page.wait_for_selector('#stage.has-image')
        page.locator('input[name=position][value=custom]').check()
        check(tag + " 2 custom area control", page.locator("#customCoords").is_visible())
        canvas = page.locator("#regionCanvas")
        check(tag + " 2 canvas overlay", canvas.is_visible())
        box = canvas.bounding_box()

        def drag(x1, y1, x2, y2):
            page.mouse.move(box["x"] + box["width"] * x1,
                            box["y"] + box["height"] * y1)
            page.mouse.down()
            page.mouse.move(box["x"] + box["width"] * x2,
                            box["y"] + box["height"] * y2, steps=6)

        drag(0.25, 0.25, 0.75, 0.75)
        check(tag + " 2 live drag box",
              page.locator("#zone").evaluate("el => el.style.width") == "50%")
        page.mouse.up()
        check(tag + " 2 normalized coords saved",
              page.input_value("#mask_coords") == "0.25,0.25,0.75,0.75",
              page.input_value("#mask_coords"))
        drag(0.4, 0.4, 0.405, 0.405)
        page.mouse.up()
        check(tag + " 2 tiny drag rejected",
              "too small" in page.locator("#regionStatus").inner_text().lower()
              and not page.input_value("#mask_coords"),
              page.locator("#regionStatus").inner_text())
        drag(0.25, 0.25, 0.75, 0.75)
        page.mouse.up()
        page.click("#clearRegion")
        check(tag + " 2 clear selection",
              not page.input_value("#mask_coords")
              and page.locator("#zone").evaluate("el => el.style.width") != "50%")
        drag(0.25, 0.25, 0.75, 0.75)
        page.mouse.up()
        check(tag + " 2 drag-select interaction",
              page.input_value("#mask_coords") == "0.25,0.25,0.75,0.75"
              and page.locator("#zone").evaluate("el => el.style.width") == "50%"
              and "too small" not in page.locator("#regionStatus").inner_text().lower(),
              (page.input_value("#mask_coords"),
               page.locator("#zone").evaluate("el => el.style.width")))
        shot(page, "14-custom-area")
        shot_path = os.path.join("docs", "screenshots", "14-custom-area.png")
        check(tag + " 2 custom area screenshot", os.path.isfile(shot_path), shot_path)
        page.locator('input[name=position][value=middle_center]').check()
        check(tag + " 2 preset ignores custom",
              not page.input_value("#mask_coords") and not canvas.is_visible())

        # Freehand paint: strokes, eraser, touch/pen, clear and preset fallback.
        check(tag + " 2 paint option and default preset",
              page.locator('input[name=position][value=painted]').count() == 1
              and page.locator('input[name=position][value=middle_center]').is_checked())
        page.locator('input[name=position][value=painted]').check()
        paint_canvas = page.locator("#paintCanvas")
        check(tag + " 2 paint controls",
              page.locator("#paintControls").is_visible()
              and paint_canvas.is_visible()
              and not page.locator("#zone").is_visible())
        paint_box = paint_canvas.bounding_box()

        def paint_stroke(x1, y1, x2, y2):
            page.mouse.move(paint_box["x"] + paint_box["width"] * x1,
                            paint_box["y"] + paint_box["height"] * y1)
            page.mouse.down()
            page.mouse.move(paint_box["x"] + paint_box["width"] * x2,
                            paint_box["y"] + paint_box["height"] * y2, steps=8)
            page.mouse.up()

        def white_pixels():
            return page.evaluate("""() => {
                const c = document.getElementById('maskExportCanvas');
                const data = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
                let count = 0;
                for (let i = 0; i < data.length; i += 4) if (data[i] > 127) count++;
                return count;
            }""")

        paint_stroke(0.20, 0.25, 0.70, 0.25)
        first_count = white_pixels()
        check(tag + " 2 painted stroke exports PNG",
              page.input_value("#painted_mask").startswith("data:image/png;base64,")
              and first_count > 0, first_count)

        page.click("#eraserMode")
        check(tag + " 2 eraser mode",
              page.locator("#eraserMode").get_attribute("aria-pressed") == "true"
              and page.locator("#brushMode").get_attribute("aria-pressed") == "false")
        paint_stroke(0.38, 0.25, 0.52, 0.25)
        erased_count = white_pixels()
        check(tag + " 2 eraser subtracts", erased_count < first_count,
              (first_count, erased_count))

        page.click("#brushMode")
        paint_stroke(0.25, 0.45, 0.75, 0.45)
        multi_count = white_pixels()
        check(tag + " 2 multiple strokes allowed", multi_count > erased_count,
              (erased_count, multi_count))

        def synthetic_stroke(pointer_type, y):
            page.evaluate("""([pointerType, y]) => {
                const c = document.getElementById('paintCanvas');
                const r = c.getBoundingClientRect();
                const send = (type, fx) => c.dispatchEvent(new PointerEvent(type, {
                    bubbles: true, cancelable: true,
                    clientX: r.left + r.width * fx, clientY: r.top + r.height * y,
                    pointerType, pointerId: 42, isPrimary: true,
                    buttons: type === 'pointerup' ? 0 : 1
                }));
                send('pointerdown', 0.20);
                send('pointermove', 0.35);
                send('pointerup', 0.50);
            }""", [pointer_type, y])

        before_touch = white_pixels()
        synthetic_stroke("touch", 0.62)
        after_touch = white_pixels()
        synthetic_stroke("pen", 0.74)
        after_pen = white_pixels()
        check(tag + " 2 touch and pen strokes",
              after_touch > before_touch and after_pen > after_touch,
              (before_touch, after_touch, after_pen))

        shot(page, "14-painted-area")
        shot_path = os.path.join("docs", "screenshots", "14-painted-area.png")
        check(tag + " 2 painted area screenshot", os.path.isfile(shot_path), shot_path)

        page.click("#clearPaint")
        check(tag + " 2 clear painting",
              not page.input_value("#painted_mask") and white_pixels() == 0)
        page.locator('input[name=position][value=middle_center]').check()
        check(tag + " 2 preset ignores painted data",
              not page.input_value("#painted_mask") and not paint_canvas.is_visible()
              and page.locator("#zone").is_visible())
    if capture:
        shot(page, "19-step2-upload")

    # Step 3 — AI room detection and measurement.
    result = analyze_in_browser(page)
    data = result.get("data", {})
    check(tag + " 3 CV measurement", result.get("status") == 200 and all(
          key in data for key in ("width_m", "length_m", "height_m",
                                  "confidence", "note", "overlay_url")), result)
    if capture and data.get("overlay_url"):
        page.goto(BASE + data["overlay_url"])
        page.wait_for_load_state("networkidle")
        shot(page, "20-step3-measurement")

    # Step 4 — AI interior design generation (the saved result for this role).
    design_id = demo["designs"][role]
    page.goto(BASE + "/design/" + str(design_id))
    page.wait_for_selector("[data-placement]")
    page.wait_for_load_state("networkidle")
    after = page.locator(".compare img.after")
    check(tag + " 4 generated design", after.evaluate("i => i.complete && i.naturalWidth > 0")
          and "Room details" in page.content())
    if role == "customer":
        check(tag + " 4 legacy result unchanged",
              "Custom area edited" not in page.content()
              and page.locator(".mask-overlay").count() == 0)
    if capture:
        shot(page, "21-step4-result")

    # Step 5 — interactive drag-and-drop furniture, including rotation/save.
    page.locator(".palette-item[data-src]").first.click()
    page.wait_for_selector(".placed-item")
    item = page.locator(".placed-item").first
    item.locator(".rotate-right").click()
    page.wait_for_timeout(100)
    before = item.evaluate("el => el.dataset.rotation + '|' + el.style.transform")
    page.click("[data-save-placement]")
    page.wait_for_function(
        "document.querySelector('[data-placement-status]').textContent.includes('Saved 1')",
        timeout=10000)
    with sqlite3.connect(DB) as con:
        stored = json.loads(con.execute("SELECT placement_json FROM design WHERE id=?",
                                        (design_id,)).fetchone()[0])["items"]
    check(tag + " 5 furniture rotate + save", before.startswith("15|") and
          "rotate(15deg)" in before and len(stored) == 1 and
          float(stored[0]["rotation"]) == 15.0, (before, stored))
    if capture:
        shot(page, "22-step5-placement")
    page.reload()
    page.wait_for_selector(".placed-item")
    restored = page.locator(".placed-item").first.evaluate(
        "el => el.dataset.rotation + '|' + el.style.transform")
    check(tag + " 5 placement restored", restored == before, restored)
    page.click("[data-clear-placement]")
    page.click("[data-save-placement]")
    page.wait_for_function(
        "document.querySelector('[data-placement-status]').textContent.includes('Saved 0')",
        timeout=10000)

    if role == "customer":
        # A custom design gets its own label and a mask overlay in Before/After.
        with sqlite3.connect(DB) as con:
            owner_id = con.execute("SELECT id FROM user WHERE username=?",
                                   (demo["cust"],)).fetchone()[0]
            custom_id = con.execute(
                "INSERT INTO design (user_id,input_image,mask_image,output_image,prompt,"
                "position,mask_coords) VALUES (?,?,?,?,?,?,?)",
                (owner_id, "1927bef4-2d17-4252-b768-b651e25671b2.png",
                 "mask_1927bef4-2d17-4252-b768-b651e25671b2.png",
                 "output_1927bef4-2d17-4252-b768-b651e25671b2.png",
                 "browser custom area result check", "custom", "25,25,75,75"),
            ).lastrowid
        page.goto(BASE + "/design/" + str(custom_id))
        page.wait_for_load_state("networkidle")
        check(tag + " 4 custom label", "Custom area edited" in page.content())
        check(tag + " 4 mask overlay with before/after",
              page.locator(".mask-overlay").is_visible()
              and page.locator(".compare img.after").is_visible()
              and page.locator(".tag.l").inner_text() == "Before"
              and page.locator(".tag.r").inner_text() == "After")
        page.click("#toggleMask")
        hidden = not page.locator(".mask-overlay").is_visible()
        pressed = page.locator("#toggleMask").get_attribute("aria-pressed")
        check(tag + " 4 hide mask", hidden and pressed == "false",
              (hidden, pressed, page.locator("[data-compare]").get_attribute("class")))
        page.click("#toggleMask")
        check(tag + " 4 show mask", page.locator(".mask-overlay").is_visible())

        with sqlite3.connect(DB) as con:
            painted_id = con.execute(
                "INSERT INTO design (user_id,input_image,mask_image,output_image,prompt,"
                "position,mask_coords) VALUES (?,?,?,?,?,?,?)",
                (owner_id, "1927bef4-2d17-4252-b768-b651e25671b2.png",
                 "mask_1927bef4-2d17-4252-b768-b651e25671b2.png",
                 "output_1927bef4-2d17-4252-b768-b651e25671b2.png",
                 "browser painted area result check", "painted", ""),
            ).lastrowid
        page.goto(BASE + "/design/" + str(painted_id))
        page.wait_for_load_state("networkidle")
        check(tag + " 4 painted label", "Custom painted area edited" in page.content())
        check(tag + " 4 painted mask preview",
              page.locator(".mask-overlay").is_visible()
              and page.locator(".mask-preview").count() == 1
              and page.locator(".mask-preview").is_visible())
        page.click("#toggleMask")
        painted_hidden = not page.locator(".mask-overlay").is_visible()
        painted_pressed = page.locator("#toggleMask").get_attribute("aria-pressed")
        check(tag + " 4 painted mask toggle", painted_hidden and painted_pressed == "false",
              (painted_hidden, painted_pressed))

    # Step 6 — product details and shop connection.
    pid = demo["products"][0][0]
    page.goto(BASE + "/products")
    page.wait_for_load_state("networkidle")
    catalogue = page.locator("body").inner_text()
    check(tag + " 6 catalogue shop", "Demo Interiors" in catalogue and "Bengaluru" in catalogue)
    page.goto(BASE + "/products/" + str(pid))
    page.wait_for_selector(".detail-grid")
    body = page.locator("body").inner_text()
    expected = ["Demo Interiors", "Bengaluru", "9876543210"]
    expected.append("Ask shop owner" if role in ("customer", "designer")
                    else "Manage catalogue")
    check(tag + " 6 product + shop contact", all(text in body for text in expected), body[:120])
    if capture:
        shot(page, "23-step6-product")
    else:
        shot(page, ROLE_WALK_SHOT[role])
    if role == "customer":
        page.fill("#message", "Please share the delivery time.")
        page.click('button:has-text("Send to shop")')
        page.wait_for_load_state("networkidle")
        check(tag + " 6 enquiry sent", "sent to Demo Interiors" in
              page.locator("body").inner_text())


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

            page.goto(BASE + "/my/enquiries")
            page.wait_for_load_state("networkidle")
            shot(page, "16-my-enquiries")
            check("customer enquiries page", "My enquiries" in page.content() and
                  "Could you share the dimensions?" in page.content())

            # Admin pages
            login(page, demo["admin"])
            for path, name, marker in [
                ("/admin", "10-admin-dashboard", "Admin dashboard"),
                ("/admin/users", "11-admin-users", "All accounts"),
                ("/admin/shops", "12-admin-shops", "Shop owners"),
                ("/admin/shops/" + str(demo["shop_id"]), "13-admin-shop", "catalogue"),
                ("/admin/reports", "14-admin-reports", "Platform reports"),
                ("/admin/products", "15-product-moderation", "Product moderation"),
            ]:
                page.goto(BASE + path)
                page.wait_for_load_state("networkidle")
                shot(page, name)
                check("admin page " + path, marker in page.content())

            # Full six-step PDF walkthrough for each of the four roles.
            for role, key, capture in [
                ("customer", "cust", True),
                ("admin", "admin", False),
                ("designer", "designer", False),
                ("shop_owner", "shop", False),
            ]:
                pdf_walkthrough(page, demo, role, demo[key], capture)

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

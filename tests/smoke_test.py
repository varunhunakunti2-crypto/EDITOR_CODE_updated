"""End-to-end smoke test for the running Flask app.

Run from the project folder while the server is up:
    python tests/smoke_test.py

It registers temporary accounts, exercises every role-gated feature and
removes all of its own data afterwards. Only Python's standard library is
required.
"""
import http.cookiejar
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = os.environ.get("APP_BASE_URL", "http://127.0.0.1:5000")
DB = os.path.join("instance", "interior_design.db")
PASS, FAIL = [], []


def check(label, ok, detail=""):
    (PASS if ok else FAIL).append(label)
    print(("PASS " if ok else "FAIL ") + label + ((" | " + str(detail)) if detail else ""), flush=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def openers():
    jar = http.cookiejar.CookieJar()
    return (urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)),
            urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect()))


def request(op, path, data=None, ctype=None):
    headers = {"Content-Type": ctype} if ctype else {}
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with op.open(req, timeout=90) as r:
            return r.status, r.headers.get("Location"), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location"), e.read().decode("utf-8", "replace")


def post(op, path, fields):
    return request(op, path, urllib.parse.urlencode(fields).encode(),
                   "application/x-www-form-urlencoded")


def multipart(fields, filename, image):
    boundary = "----smoke" + uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
            f"filename=\"{filename}\"\r\nContent-Type: image/jpeg\r\n\r\n").encode()
    body += image + b"\r\n"
    for key, value in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n"
                 f"{value}\r\n").encode()
    body += (f"--{boundary}--\r\n").encode()
    return body, "multipart/form-data; boundary=" + boundary


def make_user(prefix, role):
    follow, strict = openers()
    username = prefix + uuid.uuid4().hex[:6]
    post(follow, "/register", {"username": username, "email": username + "@t.local",
                               "password": "pass123", "role": role})
    post(strict, "/login", {"username": username, "password": "pass123"})
    return follow, strict, username


def wait_for_server():
    for _ in range(40):
        try:
            request(openers()[0], "/model-status")
            return True
        except Exception:
            time.sleep(1)
    return False


def main():
    if not wait_for_server():
        print("Server is not reachable at " + BASE)
        return 1

    created_users, product_images = [], []

    # --- Public pages and health -----------------------------------------
    anon, anon_strict = openers()
    st, _, body = request(anon, "/model-status")
    state = json.loads(body)
    check("model-status endpoint", st == 200 and not state.get("error"), state)
    for path in ["/", "/login", "/register"]:
        check("public " + path, request(anon, path)[0] == 200)
    check("anonymous dashboard blocked",
          request(anon_strict, "/dashboard")[0] == 302)
    check("anonymous my enquiries blocked",
          request(anon_strict, "/my/enquiries")[0] == 302)

    # --- Roles ------------------------------------------------------------
    admin_f, admin_s, admin_u = make_user("smoke_admin_", "customer")
    shop_f, shop_s, shop_u = make_user("smoke_shop_", "shop_owner")
    cust_f, cust_s, cust_u = make_user("smoke_cust_", "customer")
    design_f, design_s, design_u = make_user("smoke_design_", "designer")
    created_users += [admin_u, shop_u, cust_u, design_u]

    with sqlite3.connect(DB) as con:
        admin_id = con.execute("SELECT id FROM user WHERE username=?", (admin_u,)).fetchone()[0]
        shop_id = con.execute("SELECT id FROM user WHERE username=?", (shop_u,)).fetchone()[0]
        cust_id = con.execute("SELECT id FROM user WHERE username=?", (cust_u,)).fetchone()[0]
        con.execute("UPDATE user SET role='admin' WHERE id=?", (admin_id,))
    post(admin_s, "/login", {"username": admin_u, "password": "pass123"})

    # --- Shop registration / verification ---------------------------------
    st, _, html = request(shop_f, "/shop/profile")
    check("shop profile form", st == 200 and "shop_name" in html)
    st, loc, _ = post(shop_s, "/shop/profile", {
        "shop_name": "Smoke Interiors", "city": "Bengaluru",
        "address": "1 Test Street", "phone": "9876543210"})
    check("shop profile submitted", st == 302 and loc.endswith("/shop"), (st, loc))
    with sqlite3.connect(DB) as con:
        verified = con.execute("SELECT verified FROM shop_profile WHERE owner_id=?",
                               (shop_id,)).fetchone()
    check("new shop starts pending", verified and verified[0] == 0, verified)
    st, _, html = request(shop_f, "/shop")
    check("dashboard shows pending shop", "Pending verification" in html)

    for label, op, expected in [("admin", admin_s, "/admin"),
                                ("shop owner", shop_s, "/shop"),
                                ("customer", cust_s, "/dashboard"),
                                ("designer", design_s, "/dashboard")]:
        st, loc, _ = post(op, "/login", {"username": {"admin": admin_u, "shop owner": shop_u,
                                                      "customer": cust_u, "designer": design_u}[label],
                                         "password": "pass123"})
        check(f"{label} login redirects to {expected}", st == 302 and (loc or "").endswith(expected), (st, loc))

    for label, op in [("customer", cust_s), ("designer", design_s)]:
        for path in ["/admin", "/admin/users", "/admin/shops", "/admin/reports",
                     "/admin/products", "/shop", "/shop/products"]:
            st, loc, _ = request(op, path)
            check(f"{label} blocked from {path}", st == 302 and loc.endswith("/dashboard"), (st, loc))
    for path in ["/admin", "/admin/users", "/admin/shops", "/admin/reports",
                 "/admin/products", "/shop", "/shop/products"]:
        check("admin can open " + path, request(admin_f, path)[0] == 200)
    check("customer can open my enquiries", request(cust_f, "/my/enquiries")[0] == 200)
    check("designer can open my enquiries", request(design_f, "/my/enquiries")[0] == 200)

    # --- Schema and legacy designs ----------------------------------------
    with sqlite3.connect(DB) as con:
        columns = [row[1] for row in con.execute("PRAGMA table_info(design)")]
        legacy_ids = [row[0] for row in con.execute(
            "SELECT id FROM design ORDER BY id LIMIT 8")]
        blank_coords = con.execute(
            "SELECT COUNT(*) FROM design WHERE id <= 8 "
            "AND (mask_coords IS NULL OR mask_coords = '')").fetchone()[0] if legacy_ids else 0
    check("design schema has new fields", all(name in columns for name in
          ["room_type", "style", "budget", "preferences", "width_m",
           "length_m", "height_m", "detection_notes", "placement_json",
           "mask_coords"]))
    legacy_pages = [request(admin_f, f"/design/{design_id}") for design_id in legacy_ids]
    check("old 8 designs still open", len(legacy_ids) == 8 and all(
          page[0] == 200 for page in legacy_pages), legacy_ids)
    check("old designs keep blank mask coords", blank_coords == len(legacy_ids),
          blank_coords)
    check("legacy result pages have no custom UI", all(
          "Custom area edited" not in page[2] and "mask-overlay" not in page[2]
          for page in legacy_pages))

    # --- Analysis API (Step 2/3) -----------------------------------------

    photo = open("sample.jpg", "rb").read()
    body, ctype = multipart({"reference_pixels": "180"}, "room.jpg", photo)
    st, _, payload = request(cust_f, "/api/analyze-room", body, ctype)
    try:
        analysis = json.loads(payload)
    except ValueError:
        analysis = {}
    check("analysis API returns dimensions", st == 200 and all(
          key in analysis for key in ("width_m", "length_m", "height_m",
                                      "confidence", "note", "overlay_url")), payload[:160])
    check("analysis overlay is served", str(analysis.get("overlay_url", "")).startswith(
          "/static/uploads/analysis/"), analysis.get("overlay_url"))
    body, ctype = multipart({"width_m": "5.5", "length_m": "6.2", "height_m": "2.8"},
                            "room.jpg", photo)
    st, _, payload = request(cust_f, "/api/analyze-room", body, ctype)
    manual = json.loads(payload) if st == 200 else {}
    check("analysis manual overrides applied",
          (manual.get("width_m"), manual.get("length_m"), manual.get("height_m"))
          == (5.5, 6.2, 2.8), manual)
    st, _, payload = request(cust_f, "/api/analyze-room", b"",
                             "multipart/form-data; boundary=none")
    check("analysis rejects missing image", st == 400 and "error" in payload, payload[:120])
    body, ctype = multipart({}, "room.txt", b"not an image")
    check("analysis rejects bad file type",
          request(cust_s, "/api/analyze-room", body, ctype)[0] == 400)
    check("anonymous analysis blocked", request(anon_strict, "/api/analyze-room",
          body, ctype)[0] == 302)

    # A design row with all new fields: result page + placement persistence.
    with sqlite3.connect(DB) as con:
        design_id = con.execute(
            "INSERT INTO design (user_id,input_image,mask_image,output_image,prompt,position,"
            "room_type,style,budget,preferences,width_m,length_m,height_m,detection_notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cust_id, "61764adc-42b9-4ec0-bbe3-5ee6358d8a05.jpg",
             "mask_61764adc-42b9-4ec0-bbe3-5ee6358d8a05.jpg",
             "output_61764adc-42b9-4ec0-bbe3-5ee6358d8a05.jpg",
             "add a wooden bookshelf", "whole_room", "living_room", "modern",
             "50000 INR", "warm colours", 4.5, 5.0, 2.7,
             "Estimated from a 2 m door reference."),
        ).lastrowid
    st, _, html = request(cust_f, f"/design/{design_id}")
    check("result shows new room fields", st == 200 and all(text in html for text in
          ["Living room", "Modern", "50000 INR", "warm colours",
           "W 4.50 m", "L 5.00 m", "H 2.70 m",
           "Estimated from a 2 m door reference."]))
    check("result shows accuracy disclaimer", "approximate" in html)
    check("other customer cannot open design",
          request(design_s, f"/design/{design_id}")[0] == 404)
    check("admin can open any design", request(admin_f, f"/design/{design_id}")[0] == 200)

    placement_url = f"/design/{design_id}/placement"
    placement_body = json.dumps({"items": [{
        "src": "/static/uploads/products/lamp.jpg", "name": "Lamp",
        "rx": 0.3, "ry": 0.7, "scale": 0.25, "rotation": 90,
    }]}).encode()
    st, _, payload = request(cust_f, placement_url, placement_body, "application/json")
    check("placement saved over HTTP", st == 200 and json.loads(payload).get("count") == 1,
          payload[:120])
    with sqlite3.connect(DB) as con:
        saved = json.loads(con.execute("SELECT placement_json FROM design WHERE id=?",
                                       (design_id,)).fetchone()[0])["items"]
    check("placement fields and rotation stored", saved and all([
          saved[0]["src"] == "/static/uploads/products/lamp.jpg",
          saved[0]["name"] == "Lamp", saved[0]["rx"] == 0.3,
          saved[0]["ry"] == 0.7, saved[0]["scale"] == 0.25,
          saved[0]["rotation"] == 90.0]), saved)
    st, _, html = request(cust_f, f"/design/{design_id}")
    check("result restores saved placement", st == 200 and
          "/static/uploads/products/lamp.jpg" in html and "rotation" in html)
    check("non-owner placement rejected", request(design_s, placement_url,
          placement_body, "application/json")[0] == 403)
    check("admin placement allowed", request(admin_f, placement_url,
          json.dumps({"items": []}).encode(), "application/json")[0] == 200)
    check("malformed placement rejected", request(cust_f, placement_url,
          b'{}', "application/json")[0] == 400)
    check("anonymous placement blocked", request(anon_strict, placement_url,
          placement_body, "application/json")[0] == 302)

    # --- Products ---------------------------------------------------------
    image = open(os.path.join("sample.jpg"), "rb").read()
    body, ctype = multipart({"name": "Smoke Test Lamp", "category": "Lighting",
                             "price": "1234.50", "dimensions": "30 x 30 x 140 cm",
                             "description": "A test lamp."}, "lamp.jpg", image)
    st, loc, _ = request(shop_s, "/shop/products/add", body, ctype)
    check("product upload", st == 302 and loc.endswith("/shop/products"), (st, loc))
    with sqlite3.connect(DB) as con:
        row = con.execute("SELECT id, image_file FROM product WHERE name=?",
                          ("Smoke Test Lamp",)).fetchone()
    check("product row created", bool(row))
    pid, pimage = row
    product_images.append(pimage)
    check("product image saved", os.path.isfile(os.path.join("static", "uploads", "products", pimage)))

    st, _, html = request(shop_f, "/shop/products")
    check("owner product list", st == 200 and "Smoke Test Lamp" in html and "/products/" + str(pid) in html)
    check("owner list shows shop details", all(text in html for text in
          ["Smoke Interiors", "Bengaluru", "9876543210", "1 Test Street", shop_u + "@t.local"]))
    st, _, html = request(shop_f, "/products/" + str(pid))
    check("owner product detail", st == 200 and "Manage catalogue" in html and "1234.50" in html)
    st, _, html = request(cust_f, "/products")
    check("pending shop product hidden", st == 200 and "Smoke Test Lamp" not in html)
    check("pending product detail 404", request(cust_s, f"/products/{pid}")[0] == 404)
    st, _, html = request(admin_f, "/admin/shops/" + str(shop_id))
    check("admin shop catalogue", st == 200 and "Smoke Test Lamp" in html)

    st, loc, _ = post(admin_s, f"/admin/shops/{shop_id}/verify", {"verified": "1"})
    check("admin verifies shop", st == 302 and loc.endswith(f"/admin/shops/{shop_id}"), (st, loc))
    with sqlite3.connect(DB) as con:
        verified = con.execute("SELECT verified FROM shop_profile WHERE owner_id=?",
                               (shop_id,)).fetchone()
    check("shop now verified", verified and verified[0] == 1, verified)
    st, _, html = request(cust_f, "/products")
    check("public catalogue", st == 200 and "Smoke Test Lamp" in html)
    check("catalogue shows verified shop", "Smoke Interiors" in html and "Bengaluru" in html)
    st, _, html = request(cust_f, "/products/" + str(pid))
    check("public product detail", st == 200 and "30 x 30 x 140 cm" in html and "Place in my design" in html)
    check("detail shows verified shop contact", all(text in html for text in
          ["Smoke Interiors", "Bengaluru", "9876543210", "1 Test Street", shop_u + "@t.local"]))
    check("ask shop owner form offered", "Ask shop owner" in html and
          "/products/" + str(pid) + "/enquire" in html)
    check("unknown product 404", request(cust_s, "/products/999999")[0] == 404)

    # --- Product editing, availability and enquiries ----------------------
    st, _, html = request(shop_f, f"/shop/products/{pid}/edit")
    check("edit form prefilled", st == 200 and "Smoke Test Lamp" in html and "1234.50" in html)
    st, loc, _ = post(shop_s, f"/shop/products/{pid}/edit", {
        "name": "Smoke Test Lamp", "category": "Lighting", "price": "1500.00",
        "dimensions": "30 x 30 x 140 cm", "description": "Updated description.",
        "availability": "made_to_order"})
    check("product edit saved", st == 302 and loc.endswith("/shop/products"), (st, loc))
    with sqlite3.connect(DB) as con:
        row = con.execute("SELECT price, description, availability FROM product WHERE id=?",
                          (pid,)).fetchone()
    check("product fields updated",
          row == (1500.0, "Updated description.", "made_to_order"), row)

    st, loc, _ = post(shop_s, f"/shop/products/{pid}/availability",
                      {"availability": "out_of_stock"})
    check("availability toggled", st == 302 and loc.endswith("/shop/products"), (st, loc))
    with sqlite3.connect(DB) as con:
        state = con.execute("SELECT availability FROM product WHERE id=?", (pid,)).fetchone()[0]
    check("availability is out of stock", state == "out_of_stock", state)
    post(shop_s, f"/shop/products/{pid}/availability", {"availability": "in_stock"})

    st, loc, _ = post(cust_s, f"/products/{pid}/enquire",
                      {"kind": "enquiry", "message": "Is this available in walnut?"})
    check("customer sends enquiry", st == 302 and loc.endswith(f"/products/{pid}"), (st, loc))
    with sqlite3.connect(DB) as con:
        enq = con.execute("SELECT id, status FROM enquiry WHERE product_id=?", (pid,)).fetchone()
    check("enquiry stored as new", enq and enq[1] == "new", enq)
    st, _, html = request(cust_f, "/my/enquiries")
    check("customer sees own enquiry as new",
          st == 200 and "Is this available in walnut?" in html and "New" in html)
    st, _, html = request(design_f, "/my/enquiries")
    check("other customer cannot see enquiry", "Is this available in walnut?" not in html)
    st, _, html = request(shop_f, "/shop/enquiries")
    check("owner inbox shows enquiry", st == 200 and "Is this available in walnut?" in html)
    st, loc, _ = post(cust_s, f"/shop/enquiries/{enq[0]}/status", {"status": "closed"})
    check("customer cannot change status", st == 302 and loc.endswith("/dashboard"), (st, loc))
    st, loc, _ = post(shop_s, f"/shop/enquiries/{enq[0]}/status", {"status": "responded"})
    check("owner updates enquiry status", st == 302 and loc.endswith("/shop/enquiries"), (st, loc))
    with sqlite3.connect(DB) as con:
        state = con.execute("SELECT status FROM enquiry WHERE id=?", (enq[0],)).fetchone()[0]
    check("enquiry status persisted", state == "responded", state)
    st, _, html = request(cust_f, "/my/enquiries")
    check("customer sees responded status",
          st == 200 and "Is this available in walnut?" in html and "Responded" in html)

    # Enquiry details: validation, kind fallback and a linked design.
    enquire_url = f"/products/{pid}/enquire"
    with sqlite3.connect(DB) as con:
        before = con.execute("SELECT COUNT(*) FROM enquiry WHERE product_id=?", (pid,)).fetchone()[0]
    st, loc, _ = post(cust_s, enquire_url, {"message": "   "})
    with sqlite3.connect(DB) as con:
        after = con.execute("SELECT COUNT(*) FROM enquiry WHERE product_id=?", (pid,)).fetchone()[0]
    check("empty enquiry rejected", st == 302 and loc.endswith(f"/products/{pid}")
          and after == before, (st, after, before))
    post(cust_s, enquire_url, {"kind": "bogus", "message": "Unknown kind test"})
    post(cust_s, enquire_url, {"kind": "order", "message": "Order linked to design",
                               "design_id": str(design_id)})
    with sqlite3.connect(DB) as con:
        fallback = con.execute("SELECT kind FROM enquiry WHERE message=?",
                               ("Unknown kind test",)).fetchone()
        linked = con.execute("SELECT kind, design_id FROM enquiry WHERE message=?",
                             ("Order linked to design",)).fetchone()
    check("invalid enquiry kind falls back", fallback and fallback[0] == "enquiry", fallback)
    check("enquiry can link a design", linked == ("order", design_id), linked)
    st, _, html = request(shop_f, "/shop/enquiries")
    check("owner inbox shows linked order", "Order linked to design" in html and "Order" in html)

    # Flagging and verification guards.
    st, loc, _ = post(cust_s, f"/products/{pid}/flag", {})
    with sqlite3.connect(DB) as con:
        flagged = con.execute("SELECT flagged FROM product WHERE id=?", (pid,)).fetchone()[0]
    check("customer can flag a product", st == 302 and flagged == 1, (st, flagged))
    with sqlite3.connect(DB) as con:
        con.execute("UPDATE product SET flagged=0 WHERE id=?", (pid,))
    check("owner cannot flag own product", post(shop_s, f"/products/{pid}/flag", {})[0] == 403)
    check("admin cannot flag a product", post(admin_s, f"/products/{pid}/flag", {})[0] == 403)

    st, _, html = request(admin_f, "/admin/products")
    check("admin moderation queue shows flag", "Smoke Test Lamp" in html)
    st, _, _ = post(admin_s, f"/admin/shops/{shop_id}/verify", {"verified": "0"})
    with sqlite3.connect(DB) as con:
        revoked = con.execute("SELECT verified FROM shop_profile WHERE owner_id=?",
                              (shop_id,)).fetchone()[0]
    check("admin revokes shop", st == 302 and revoked == 0, (st, revoked))
    check("revoked shop product hidden", "Smoke Test Lamp" not in
          request(cust_f, "/products")[2])
    post(admin_s, f"/admin/shops/{shop_id}/verify", {"verified": "1"})
    check("re-verified shop product visible", "Smoke Test Lamp" in
          request(cust_f, "/products")[2])

    # Role guards for every route added in Steps 1-8.
    admin_paths = ["/admin", "/admin/users", "/admin/shops",
                   f"/admin/shops/{shop_id}", "/admin/products", "/admin/reports"]
    shop_paths = ["/shop", "/shop/profile", "/shop/products", "/shop/products/add",
                  f"/shop/products/{pid}/edit", "/shop/enquiries"]
    for path in admin_paths + shop_paths:
        st, loc, _ = request(cust_s, path)
        check(f"customer blocked from {path}", st == 302 and loc.endswith("/dashboard"), (st, loc))
        check(f"anonymous blocked from {path}", request(anon_strict, path)[0] == 302)
    for path in admin_paths:
        st, loc, _ = request(shop_s, path)
        check(f"shop owner blocked from {path}", st == 302 and loc.endswith("/dashboard"), (st, loc))
    for path in shop_paths:
        check(f"shop owner can open {path}", request(shop_f, path)[0] == 200)
    for path in admin_paths:
        check(f"admin can open {path}", request(admin_f, path)[0] == 200)

    post_guards = [
        ("verify a shop", f"/admin/shops/{shop_id}/verify", {"verified": "1"}, True),
        ("moderate a product", f"/admin/products/{pid}/moderate", {"action": "hide"}, True),
        ("edit a product", f"/shop/products/{pid}/edit", {"name": "Hacked"}, False),
        ("change availability", f"/shop/products/{pid}/availability",
         {"availability": "in_stock"}, False),
        ("delete a product", f"/shop/products/{pid}/delete", {}, False),
        ("change an enquiry status", f"/shop/enquiries/{enq[0]}/status",
         {"status": "closed"}, False),
    ]
    for label, path, fields, admin_only in post_guards:
        for role, op in [("customer", cust_s), ("designer", design_s)]:
            st, loc, _ = post(op, path, fields)
            check(f"{role} cannot {label}", st == 302 and loc.endswith("/dashboard"), (st, loc))
        if admin_only:
            st, loc, _ = post(shop_s, path, fields)
            check(f"shop owner cannot {label}", st == 302 and loc.endswith("/dashboard"), (st, loc))
    check("shop owner cannot flag a product", post(shop_s, f"/products/{pid}/flag", {})[0] == 403)
    check("admin can open my enquiries", request(admin_f, "/my/enquiries")[0] == 200)

    body, ctype = multipart({"name": "Bad File", "price": "10"}, "bad.txt", b"not an image")
    st, _, _ = request(shop_s, "/shop/products/add", body, ctype)
    check("invalid image type rejected", st == 302)
    with sqlite3.connect(DB) as con:
        check("bad product not saved", con.execute(
            "SELECT COUNT(*) FROM product WHERE name='Bad File'").fetchone()[0] == 0)

    st, loc, _ = request(cust_s, f"/shop/products/{pid}/delete", b"", "application/x-www-form-urlencoded")
    check("customer cannot delete product", st == 302 and loc.endswith("/dashboard"))

    st, loc, _ = request(shop_s, f"/shop/products/{pid}/delete", b"", "application/x-www-form-urlencoded")
    check("owner deletes product", st == 302 and loc.endswith("/shop/products"))
    with sqlite3.connect(DB) as con:
        check("product row deleted", con.execute("SELECT COUNT(*) FROM product WHERE id=?", (pid,)).fetchone()[0] == 0)
    check("product image deleted", not os.path.isfile(os.path.join("static", "uploads", "products", pimage)))

    check("admin users list", all(u in request(admin_f, "/admin/users")[2] for u in [admin_u, shop_u, cust_u]))
    check("admin shops list", shop_u in request(admin_f, "/admin/shops")[2])

    # --- Cleanup ----------------------------------------------------------
    with sqlite3.connect(DB) as con:
        ids = [con.execute("SELECT id FROM user WHERE username=?", (u,)).fetchone()[0]
               for u in created_users]
        marks = ",".join("?" * len(ids))
        con.execute(f"DELETE FROM enquiry WHERE customer_id IN ({marks}) "
                    f"OR shop_owner_id IN ({marks})", ids + ids)
        con.execute(f"DELETE FROM shop_profile WHERE owner_id IN ({marks})", ids)
        con.execute(f"DELETE FROM design WHERE user_id IN ({marks})", ids)
        con.execute(f"DELETE FROM user WHERE id IN ({marks})", ids)
    for name in product_images:
        try:
            os.remove(os.path.join("static", "uploads", "products", name))
        except OSError:
            pass

    print("\nSUMMARY:", len(PASS), "passed,", len(FAIL), "failed")
    if FAIL:
        print("FAILED:", FAIL)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# AI Interior Designer

A Flask app that turns a photo of a room into a design preview with local
Stable Diffusion inpainting, then suggests nearby shops using Gemini. It also
includes role-based dashboards, a shop-owner product catalogue and drag-and-drop
furniture placement.

**Repository:** https://github.com/varunhunakunti2-crypto/EDITOR_CODE_updated

## Quick start
    git clone https://github.com/varunhunakunti2-crypto/EDITOR_CODE_updated.git
    cd EDITOR_CODE_updated
    python -m venv .venv && .venv\Scripts\activate      # Windows
    pip install -r requirements.txt
    copy .env.example .env                              # then edit the values
    python app.py        # open http://localhost:5000 (use localhost — the microphone needs it)

On macOS/Linux use `source .venv/bin/activate` and `cp .env.example .env`.
The first design request downloads the inpainting model (a few GB) and loads it
in the background; `/model-status` reports progress.

## Settings (.env)

Copy `.env.example` to `.env` and fill in your values. `.env` is gitignored; only
the placeholder template is committed.

- `SECRET_KEY` — Flask session secret; use a long random string.
- `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_TIMEOUT` — nearby-shop suggestions. The default model is `gemini-3.5-flash-lite` (fast, ~2s); if it fails the app tries `gemini-3.5-flash` then `gemini-flash-latest`.
- `SD_MODEL_ID`, `SD_DEVICE` — local inpainting, described below.
- `REPLICATE_API_TOKEN` — optional, only used by the standalone `code1_api.py` example; the Flask app does not call Replicate.

The local inpainting model is configured with SD_MODEL_ID (default `runwayml/stable-diffusion-inpainting`, a public repo — the old `stabilityai/stable-diffusion-2-inpainting` now returns 401) and SD_DEVICE (`auto`, `cuda` or `cpu`). It is downloaded on first use; startup does not block. Check `/model-status` to see whether it is loading, ready, or what error occurred. A failed load is retried on the next design request.

## Roles and dashboards
Sign-up lets a user choose Customer, Interior designer or Shop owner. The first account created automatically becomes Admin (admin cannot be self-selected). Each role has its own landing page:

- Admin → `/admin` — user/role counts, account list and recent designs
- Customer / Interior designer → `/dashboard` — the design workspace
- Shop owner → `/shop` — storefront home with catalogue links and product count

Routes are protected by role; admins may open every dashboard. Existing accounts are migrated to `customer` automatically.

## Shop owner product catalogue
Shop owners can build a real product catalogue:

- `/shop/products` — product grid with counts, availability badges and delete actions
- `/shop/products/add` — multipart upload form for name, category, price, dimensions, availability, description and a PNG/JPG/JPEG image (max 16 MB)
- Images are stored in `static/uploads/products/`; deleting a product removes both its row and its image file

Each shop owner sees only their own products; admins can open every catalogue. Customers/designers are redirected away from all product routes.

## Drag-and-drop furniture placement
The result page (`/design/<id>`) has a "Place furniture" panel:

- Drag catalogue items from the palette onto the result image, or click an item to drop it in the centre
- Drop an image file from your desktop, or use "Your image" in the palette
- Drag placed items to move them; scroll over an item to resize; use × to remove one; Clear removes all
- "Download design" flattens the arranged items onto the original result and saves a PNG

The placement preview can also be saved to the design record with the Save
placement button (see below).

## Room measurement (OpenCV)
`room_analysis.py` measures a room from one photo with Canny edges + Hough
lines, converts pixels to metres using a known reference (a 2 m door by
default), writes an annotated overlay and returns width × length × height with
a confidence note. Length/depth is a proportion-based estimate — supply a
manual override when it matters:

    python room_analysis.py room.jpg --reference-pixels 180
    python room_analysis.py room.jpg --width 5.5 --length 6 --height 2.8

Python API: `analyze_room(path, reference_length_m=2, reference_pixels=180,
manual={'length_m': 6})`. The result includes `width_m`, `length_m`,
`height_m`, `confidence`, `note`, `reference`, detected corners and an
`overlay_path` under `static/uploads/analysis/`.

The design form calls `POST /api/analyze-room` (login required) with the photo
and optional `reference_pixels`; it returns the same dimensions as JSON plus an
`overlay_url`, and fills editable width/length/height inputs.

## Room-aware design generation
The design form now records room type, style, budget, preferences and measured
dimensions. `prompt_builder.py` combines them with the user's prompt before
inpainting; the original prompt stays in the database row and the result page
shows the room summary. Two edit modes are supported:

- **Add one item in a zone** — the existing nine-zone mask
- **Redesign the whole room** — a fully white mask (`whole_room` position)

Furniture arrangements are saved with `POST /design/<id>/placement` (JSON with
an `items` list; design owner or admin only) and restored when the result page
is reopened. The Save placement button in the placement panel calls this route.

## Shop verification, catalogue and enquiries
- `/shop/profile` — shop name, city, address and phone. Submitting resets the
  status to **pending**; products stay private until an admin approves the shop.
- `/admin/shops/<owner_id>/verify` — admin verifies or revokes a shop. Existing
  shops from older databases are migrated as already verified, so their products
  never disappear.
- `/products` and `/products/<id>` — only show products from verified shops
  (owners still see their own pending items; admins see everything). The catalogue
  shows the verified shop name and city; the detail page also shows address,
  phone and email.
- `/shop/products` — the owner's catalogue now includes a shop identity panel
  with the same verified name, city and contact details shown to customers.
- `/shop/products/<id>/edit` — edit name, category, price, description,
  dimensions and availability; the image can be kept or replaced.
- `/shop/products/<id>/availability` — set in stock / out of stock / made to
  order. The product list has a select and Update button for each item.
- `/products/<id>/enquire` — the **Ask shop owner** form sends an enquiry or
  order (optionally linked to one of the customer's designs) to the shop owner.
- `/my/enquiries` — customer/designer list of their own messages and orders with
  the live status set by the shop owner.
- `/shop/enquiries` — owner/admin inbox with new / responded / closed status
  updates via `/shop/enquiries/<id>/status`.

## Admin lists, moderation and reports
- `/admin/users` — full user list with roles, design/product counts and shop links
- `/admin/shops` — verification status, product counts and **Verify / Revoke** buttons (POST, admin only); `/admin/shops/<owner_id>` opens one shop's catalogue and profile
- `/admin/products` — moderation queue with flagged items first; hide, restore or permanently remove products via `POST /admin/products/<id>/moderate`
- `/products/<id>/flag` — customers can flag a listing for review; hidden products disappear from the public catalogue
- `/admin/reports` — live counts by user role, shop verification, products/availability, designs by room type and style, and enquiries by kind/status
- Admin dashboard and reports include an activity panel: pending shops, recent designs and recent enquiries
- `/products` — furniture catalogue for any logged-in user; `/products/<product_id>` shows full details (price, category, dimensions, availability, description, seller) with a "Place in my design" shortcut

Admin routes are role-protected; non-admins are redirected to their dashboard.

## New features
- Voice or typed prompt: mic button records in the browser, the server transcribes it with SpeechRecognition (Google web recognizer, needs internet).
- Nine placement buttons (top/middle/bottom x left/centre/right). The chosen spot becomes the white inpainting mask, so only that area is edited.
- Enter a city/area (or "Use my location") and Gemini suggests nearby stores for the item, shown on the result page with Google Maps links.
- Old databases are upgraded automatically with the new columns.

## Project layout

- `app.py` — routes, role guards, Gemini integration and lazy AI model loading
- `database.py` — SQLAlchemy models and automatic schema upgrades
- `room_analysis.py` — OpenCV room measurement and annotated overlays
- `prompt_builder.py` — combines room details with the user's prompt
- `templates/`, `static/` — UI, styles and client-side placement (`static/JS/placement.js`)
- `tests/` — smoke suite and Playwright browser/screenshot suite
- `docs/screenshots/` — generated UI captures
- `instance/interior_design.db` — local SQLite data, created automatically and not committed
- `.env` / `.env.example` — local secrets / safe template

Generated uploads (`uploads/`, `static/uploads/`) and Python caches are also
gitignored.

## Testing

Start the app first (`python app.py`), then run the suites from the project folder:

    python tests/smoke_test.py       # 76 HTTP/DB checks, standard library only
    python tests/browser_check.py    # 15 real-browser checks + 16 screenshots
    python tests/room_analysis_check.py  # OpenCV measurement checks, no server needed
    python tests/backend_check.py    # in-process API/DB checks, stubbed AI, no server needed
    python tests/flow_check.py       # full analyze -> design -> result flow in a browser
    python tests/shop_flow_check.py  # shop register -> verify -> catalogue/edit/enquiry flow
    python tests/admin_check.py      # verification, moderation and report counts, no server needed

`smoke_test.py` verifies public pages, role-based redirects and guards for all four
roles, product upload/list/detail/delete, catalogue access, admin lists and file
cleanup. `browser_check.py` uses Playwright + Chromium to render every screen,
exercise drag-and-drop placement, check for console errors and failed requests,
and regenerate the screenshots below. `room_analysis_check.py` generates three
synthetic rooms with known dimensions, checks the measured size, overlays and
manual overrides, and also analyses any uploaded room photos.
`backend_check.py` posts a design with every new field, verifies the DB row and
result page, checks the whole-room mask, and exercises placement guards with a
stubbed pipeline (no diffusion or API keys needed). `flow_check.py` drives the
whole room-analysis → design → result journey in Chromium with real inpainting
(slower, ~1 minute), then removes its demo account and design. `shop_flow_check.py`
covers the full shop journey in Chromium without diffusion (fast): shop registration,
verification, catalogue visibility, shop contact details, enquiry → owner inbox →
status update → customer view, product edits and availability. `admin_check.py`
confirms report counts match the database and exercises verification, flagging,
hide/restore/remove and the pending → verified → visible customer flow.

    pip install playwright && python -m playwright install chromium

The suites create temporary demo accounts, products and a design, then delete
them (and their uploaded images) when they finish, leaving existing data intact.
Older rows with a NULL `created_at` are rendered safely via the `date` template
filter and backfilled by `upgrade_schema()` on startup.

## Screenshots

Generated by `tests/browser_check.py` into `docs/screenshots/`:

| Screen | Preview |
| --- | --- |
| Home | ![Home](docs/screenshots/01-home.png) |
| Register | ![Register](docs/screenshots/02-register.png) |
| Shop dashboard | ![Shop dashboard](docs/screenshots/03-shop-dashboard.png) |
| Product list | ![Product list](docs/screenshots/04-product-list.png) |
| Add product | ![Add product](docs/screenshots/05-add-product.png) |
| Catalogue | ![Catalogue](docs/screenshots/06-catalogue.png) |
| Product detail | ![Product detail](docs/screenshots/07-product-detail.png) |
| Result + placement | ![Placement](docs/screenshots/08-result-placement.png) |
| Customer dashboard | ![Customer dashboard](docs/screenshots/09-customer-dashboard.png) |
| Admin dashboard | ![Admin dashboard](docs/screenshots/10-admin-dashboard.png) |
| Admin users | ![Admin users](docs/screenshots/11-admin-users.png) |
| Admin shops | ![Admin shops](docs/screenshots/12-admin-shops.png) |
| Admin shop catalogue | ![Admin shop](docs/screenshots/13-admin-shop.png) |
| Admin reports | ![Admin reports](docs/screenshots/14-admin-reports.png) |
| Product moderation | ![Moderation](docs/screenshots/15-product-moderation.png) |
| My enquiries | ![My enquiries](docs/screenshots/16-my-enquiries.png) |

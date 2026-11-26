# AI Interior Designer

A Flask app that turns a photo of a room into a design preview with local
Stable Diffusion inpainting, then suggests nearby shops using Gemini. It also
includes role-based dashboards, a shop-owner product catalogue and drag-and-drop
furniture placement.

**Repository:** https://github.com/varunhunakunti2-crypto/EDITOR_CODE_updated

## Project flow (from the PDF)

The project brief describes one AI-powered platform with three main dashboards —
Admin, Customer/Interior Designer and Furniture/Interior Shop Owner — that brings
computer vision, generated room previews, interactive space planning and an online
furniture catalogue together. The PDF's "Complete Working Flow" has six numbered
steps, all implemented here:

| Step | PDF step | What happens in this app |
| --- | --- | --- |
| 1 | **User Login** — Customer / Interior Designer / Shop Owner / Admin | Sign up with one of the three selectable roles; the first account becomes Admin. Each role lands on its own dashboard. |
| 2 | **Upload Room Image** — bedroom, kitchen, living room or another space | `/design` accepts a PNG/JPG/JPEG room photo plus a typed (or spoken) prompt. |
| 3 | **AI Room Detection and Measurement** — CV identifies walls, corners and boundaries and estimates dimensions using a reference | **Analyze room** calls `/api/analyze-room`; OpenCV returns width/length/height, confidence and an annotated overlay; the inputs stay editable. |
| 4 | **AI Interior Design Generation** — use preferences, room dimensions, budget and selected style | The form records room type, style, budget, preferences, dimensions and mode (one zone, a custom rectangle, a freehand painted area or whole room); `prompt_builder.py` builds the generation prompt and local Stable Diffusion inpainting produces the preview. |
| 5 | **Interactive Drag-and-Drop Furniture** — move, rotate, resize and rearrange products from registered shops | The result page palette shows verified products; items can be dragged, moved, resized and rotated, then saved to the design and exported as a PNG. |
| 6 | **Product Details and Shop Connection** — prices, dimensions, descriptions, shop details and contact/enquire | `/products` and `/products/<id>` show verified shop identity and contact details; the **Ask shop owner** form creates an in-app enquiry; `/my/enquiries` tracks its status. |

An optional **Depth Anything V2 Small** layer can preview relative near/far depth
and add a short geometry cue to the generation prompt. It is an assistant only:
the editable PNG mask, custom areas, freehand paint and SD 1.5 inpainting remain
unchanged. The model is available by default, but its cue is only applied to
generation when **Use depth cues** is ticked.

Screenshots of every step are linked in [Screenshots](#screenshots); `tests/browser_check.py`
clicks through all six steps as all four roles.

## Setup
    git clone https://github.com/varunhunakunti2-crypto/EDITOR_CODE_updated.git
    cd EDITOR_CODE_updated
    python -m venv .venv && .venv\Scripts\activate      # Windows
    pip install -r requirements.txt
    copy .env.example .env                              # then edit the values
    python app.py        # open http://localhost:5000 (use localhost — the microphone needs it)

On macOS/Linux use `source .venv/bin/activate` and `cp .env.example .env`.
Python 3.10+ is recommended; `pip install -r requirements.txt` installs Flask,
OpenCV, PyTorch, Diffusers, SpeechRecognition and the Gemini client.

1. Create `.env` from `.env.example`. Set `SECRET_KEY`; Gemini and Replicate are optional (see below).
2. Start the app with `python app.py` and open `http://localhost:5000` — use `localhost` rather than `127.0.0.1` if you want the microphone button to work.
3. Register the first account: it automatically becomes **Admin**. Admin cannot be self-selected at signup.
4. A shop owner opens `/shop/profile`, saves shop name/city/address/phone, then an admin verifies the shop at `/admin/shops`. Only verified shops appear in the public catalogue.
5. Customers/designers can now follow the six steps above. `/model-status` reports model loading; the first design request downloads the inpainting model (a few GB) and loads it in the background.

For the automated suites, also install Chromium:

    pip install playwright && python -m playwright install chromium

## Settings (.env)

Copy `.env.example` to `.env` and fill in your values. `.env` is gitignored; only
the placeholder template is committed.

- `SECRET_KEY` — Flask session secret; use a long random string.
- `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_TIMEOUT` — nearby-shop suggestions. The default model is `gemini-3.5-flash-lite` (fast, ~2s); if it fails the app tries `gemini-3.5-flash` then `gemini-flash-latest`.
- `SD_MODEL_ID`, `SD_DEVICE` — local inpainting, described below.
- `DEPTH_ENABLED`, `DEPTH_MODEL_ID`, `DEPTH_DEVICE`, `DEPTH_MAX_SIZE` — optional relative-depth assistant. Defaults: enabled, `depth-anything/Depth-Anything-V2-Small-hf`, `auto`, `512`. Set `DEPTH_ENABLED=0` to hide it entirely. `/depth-status` reports its load state.
- `REPLICATE_API_TOKEN` — optional, only used by the standalone `code1_api.py` example; the Flask app does not call Replicate.

The local inpainting model is configured with SD_MODEL_ID (default `runwayml/stable-diffusion-inpainting`, a public repo — the old `stabilityai/stable-diffusion-2-inpainting` now returns 401) and SD_DEVICE (`auto`, `cuda` or `cpu`). It is downloaded on first use; startup does not block. Check `/model-status` to see whether it is loading, ready, or what error occurred. A failed load is retried on the next design request.

The optional depth assistant uses `depth-anything/Depth-Anything-V2-Small-hf`
(Apache 2.0, ~99 MB). With CPU-only PyTorch, install its image-processor dependency
before first use:

    pip install "torchvision==0.27.1+cpu" --index-url https://download.pytorch.org/whl/cpu

Adjust the version to match your installed `torch` if needed. The model loads lazily
on the first **Depth preview** or when a design opts into depth cues.

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
- Drag placed items to move them; scroll over an item to resize
- Rotate with the ↺ / ↻ buttons on each item, or hold Shift (or Alt) while scrolling
- Use × to remove one item; Clear removes all
- "Download design" flattens the arranged items onto the original result and saves a PNG, including each item's rotation

The placement preview can also be saved to the design record with the Save
placement button, then reopened with the same position, size and rotation.

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
shows the room summary. An optional **style reference image** can also be
uploaded: `reference_style.py` reads its palette, brightness, saturation and
edge density, and appends short aesthetic cues to the generation prompt only.
The file is saved alongside the room photo and never changes the raw prompt or
the mask. Four edit modes are supported:

- **Add one item in a zone** — the existing nine-zone mask (default: **Centre**).
- **Custom area** — choose `Custom area` and drag a rectangle directly on the
  photo preview. `static/JS/region_mask.js` draws a live box, writes normalized
  `x1,y1,x2,y2` values into the hidden `mask_coords` field, and offers a
  **Clear selection** button.
- **Paint area** — choose `Paint area` and draw freehand strokes with a mouse,
  touch or pen. `static/JS/freehand_mask.js` shows translucent white strokes on
  the preview, supports an adjustable brush, an eraser that subtracts strokes,
  multiple strokes and **Clear painting**. The hidden 512×512 canvas exports a
  black/white PNG data URL on submit, stored in the existing `mask_image`
  column; the result is labelled **Custom painted area edited**.
- **Redesign the whole room** — a fully white mask (`whole_room` position).

### Custom-area limits

| Rule | Behaviour |
| --- | --- |
| Coordinates | `x1,y1,x2,y2` measured from the top-left; `x2 > x1` and `y2 > y1` |
| Accepted formats | normalized `0–1` from the browser overlay, or `0–100` percentages |
| Minimum size | 1% of the image area; the overlay also rejects drags with either side under 2% |
| Maximum size | 85% of the image area, leaving context around the edit |
| Invalid input | missing, reversed, out-of-bounds, too small or too large values fall back to the centre zone with a friendly flash message |
| Storage | valid values are normalized to percentages such as `25,25,75,75` in `Design.mask_coords`; older rows stay empty |
| Presets | switching to any preset clears the custom coordinates and uses its original nine-zone mask |

### Paint-area rules

| Rule | Behaviour |
| --- | --- |
| Brush | 8–96 px on the hidden 512×512 mask; the slider updates the preview immediately |
| Strokes | Mouse, touch and pen pointer events; each completed stroke is kept and can overlap |
| Eraser | Removes painted white along its path, including earlier strokes |
| Export | Hidden canvas posts a PNG data URL in `painted_mask`; the form also exports on submit |
| Validation | Non-PNG, corrupt, oversized or blank images are rejected by `masking.decode_painted_mask()` |
| Threshold | Accepted PNGs are resized to the working image and converted to exact black/white pixels |
| Fallback | Invalid or empty paint data uses the normal centre zone with a friendly flash message |
| Presets | Switching to any preset (or `Custom area`) clears painted data and ignores stray PNG posts |
| Storage | `position='painted'`; `mask_coords` stays empty and the PNG reuses `Design.mask_image` |

Masks are saved as lossless PNGs: the selected area is exactly white and every
pixel outside it is black. Generated pixels are pasted back through that mask, so
everything beyond the white area keeps the original photo's pixels; only JPEG
edge bleed can affect a few pixels right at the boundary. A custom-area result
is labelled **Custom area edited** and a painted result is labelled **Custom
painted area edited**. The Before/After comparison shows the mask over the
original photo, includes a small mask preview, and has a button to hide or show
it. Older designs keep their original result layout with no custom label or
mask overlay. The legacy `static/JS/mask.js` is unused and unchanged.

Furniture arrangements are saved with `POST /design/<id>/placement` (JSON with
an `items` list; design owner or admin only) and restored when the result page
is reopened. Each item stores `src`, `name`, `rx`, `ry`, `scale` and `rotation`
(degrees, normalised to -180..180). The Save placement button calls this route.

When the result contains a detectable coloured frame (or a saved custom/painted
area), `detect_frame_box()` passes its centre and size to `static/JS/placement.js`.
Newly dropped or clicked furniture is snapped into that frame and scaled with
contain logic so its aspect ratio is kept. The **Fit to frame** button repeats the
snap for the last placed item; it is hidden when no frame is available. Saved
arrangements are restored exactly as stored and are never re-snapped.

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

## Feature summary

- **Roles and dashboards** — Admin (`/admin`), Customer/Interior Designer
  (`/dashboard`) and Shop Owner (`/shop`), with role guards on every route and
  admin override.
- **Room measurement** — OpenCV edge/line/corner detection, a 2 m reference by
  default, editable overrides, annotated overlay and a confidence note.
- **Room-aware generation** — room type, style, budget, preferences and measured
  dimensions are combined with the user's prompt; the original prompt is kept in
  the database. Nine-zone masks, validated custom rectangles or a whole-room
  redesign are supported.
- **Furniture placement** — verified products, custom images, drag/move/resize,
  ↺/↻ or Shift+wheel rotation, save/reload persistence and rotated PNG download.
- **Shop connection** — verified shop identity and contact details, product
  edit/availability, **Ask shop owner** enquiries and customer status tracking.
- **Moderation** — shop verification/revocation, product flag/hide/remove, report
  counts and an activity panel on the admin dashboard and reports page.
- **Extras** — voice or typed prompt (mic uses the Google web recognizer),
  optional Gemini nearby-store suggestions with Maps links, and automatic
  upgrades of older databases with the new columns.

## Limitations

- **Dimensions are approximate.** A single photo cannot give true scale: width
  comes from a reference object (a 2 m door by default) and depth/length is
  estimated from typical room proportions. The result page shows an accuracy
  disclaimer; enter known measurements in the width/length/height inputs before
  ordering furniture or planning construction.
- **The model is downloaded on first use.** Inpainting uses a public Hugging Face
  model (a few GB). The first design request can take a while; CPU generation is
  much slower than GPU (`SD_DEVICE=auto` uses CUDA when available). Startup does
  not block, `/model-status` shows progress, and a failed load is retried on the
  next request.
- **Gemini is optional.** Without `GEMINI_API_KEY` (or without internet) the app
  still generates designs and shows the catalogue; only the nearby-store
  suggestions are unavailable. Suggested shops, prices and opening hours are
  AI-generated and must be confirmed with the shop.
- **Enquiries are in-app only.** Messages go to the shop owner's
  `/shop/enquiries` inbox and the customer sees the status on `/my/enquiries`.
  There is no email/SMS notification, live chat, payment, checkout or delivery
  tracking; shop owners update statuses manually.
- **Voice input needs internet** (Google web recognizer) and browser microphone
  permission; typing a prompt works offline.
- **Data stays local.** SQLite data and uploaded images live under `instance/`
  and `static/uploads/`; there is no external hosting or multi-user deployment
  layer beyond the local Flask server.

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

    python tests/smoke_test.py       # 174 HTTP/DB checks, standard library only
    python tests/browser_check.py    # 77 real-browser checks + 28 screenshots
    python tests/room_analysis_check.py  # OpenCV measurement checks, no server needed
    python tests/backend_check.py    # 69 in-process API/DB checks, stubbed AI, no server needed
    python tests/flow_check.py       # full analyze -> design -> result flow in a browser
    python tests/shop_flow_check.py  # shop register -> verify -> catalogue/edit/enquiry flow
    python tests/admin_check.py      # verification, moderation and report counts, no server needed
    python tests/placement_check.py  # rotate/resize/move, reload restore and PNG match in Chromium

`smoke_test.py` verifies public pages, role-based redirects and guards on every
new route for all four roles, the design schema fields (including `mask_coords`),
that the eight oldest designs still open with blank coordinates after the
migration and show no custom-area UI, the analysis API (including manual
overrides and errors), four custom-mask HTTP cases (valid coordinates, missing
coordinates, too-small box and preset with a stray coordinate), four painted-mask
HTTP cases (valid PNG, corrupt PNG, empty data and preset with a stray PNG), design
result fields, placement save/load with
rotation, shop verification/revocation, product edit/availability, enquiry details
and flagging, plus product upload/list/detail/delete, catalogue access, admin lists
and file cleanup. `browser_check.py` uses Playwright + Chromium to render every
screen, exercise drag-and-drop placement, check for console errors and failed
requests, and regenerate the screenshots below. It also walks through all six
steps of the project PDF (login, room upload, CV measurement, design generation,
interactive furniture with rotation, and product/shop connection) as each of the
four roles, checks the custom-area control, drag-select overlay, live box,
normalized hidden field, tiny-drag rejection, clear button and preset switching,
then paints mouse strokes, checks PNG export, eraser subtraction, multiple
strokes, synthetic touch/pen strokes, clear and preset fallback. It checks both
result labels and mask overlay toggles, and writes
`docs/screenshots/14-custom-area.png`, `docs/screenshots/14-painted-area.png`
plus a screenshot for every customer step and one per other role.
`room_analysis_check.py` generates three
synthetic rooms with known dimensions, checks the measured size, overlays and
manual overrides, and also analyses any uploaded room photos.
`backend_check.py` posts a design with every new field, verifies the DB row and
result page, checks the whole-room mask, validates custom coordinates (missing,
too small, out of bounds and reversed), confirms the custom mask and its
fallback (including normalized 0–1 browser values), stores normalised
coordinates in `mask_coords`, inspects the saved PNG
pixel by pixel to confirm white only in the chosen box (and black everywhere
else), verifies that stray coords never replace an ordinary nine-zone mask, then
decodes/thresholds painted PNGs, rejects empty, corrupt, blank and JPEG data,
saves a painted design, proves the painted pixels change while the rest of the
photo stays identical, checks its result label/preview, and confirms invalid
paint falls back and presets ignore stray PNGs. It checks that
`upgrade_schema()` is idempotent and exercises placement guards with a stubbed
pipeline (no diffusion or API keys needed). `flow_check.py` drives the
whole room-analysis → design → result journey in Chromium with real inpainting
(slower, ~1 minute), then removes its demo account and design. `shop_flow_check.py`
covers the full shop journey in Chromium without diffusion (fast): shop registration,
verification, catalogue visibility, shop contact details, enquiry → owner inbox →
status update → customer view, product edits and availability. `admin_check.py`
confirms report counts match the database and exercises verification, flagging,
hide/restore/remove and the pending → verified → visible customer flow.
`placement_check.py` places, moves, resizes and rotates an item, saves it,
reloads the design, checks the restored state and confirms the downloaded PNG
is pixel-identical to the pre-reload download; it also checks remove and clear.

    pip install playwright && python -m playwright install chromium

The suites create temporary demo accounts, products and a design, then delete
them (and their uploaded images) when they finish, leaving existing data intact.
Older rows with a NULL `created_at` are rendered safely via the `date` template
filter and backfilled by `upgrade_schema()` on startup.

## Final acceptance (this build)

Verified with the app running at `http://localhost:5000` and the local inpainting
model loaded (`/model-status` reports `runwayml/stable-diffusion-inpainting`):

- `python tests/smoke_test.py` — **174 passed, 0 failed**, including all original
  assertions, the four custom-mask cases and the four painted-mask cases.
- `python tests/browser_check.py` — **77 passed, 0 failed**, with zero browser
  console errors and zero failed requests, including the drag-select interaction,
  painted strokes/eraser/clear/touch/pen checks, and both
  `14-custom-area.png` and `14-painted-area.png`.
- `python tests/backend_check.py` — **69 passed, 0 failed**, including custom
  coordinate validation, normalized browser values, storage, pixel-exact PNG
  masks, painted PNG validation/thresholding, proof that generated pixels stay
  inside the white area while the rest of the photo is unchanged, both result
  labels/overlays, preserved nine-zone masks and idempotent schema upgrade.
- `room_analysis_check.py` **21/21**, `flow_check.py` **12/12**,
  `shop_flow_check.py` **20/20**, `admin_check.py` **28/28** and
  `placement_check.py` **14/14** also pass.
- Final browser acceptance: drag a small box → **a red sofa** → only that box
  changes; paint a freehand stroke → only the white area changes; the **Centre**
  preset reproduces the original fixed zone; the eight oldest designs still open
  with no custom-area UI.
- Manual six-step click-through in a real browser as a customer: register/login →
  upload a room photo → **Analyze room** (overlay plus editable 6.16 × 8.01 × 2.8 m
  estimate) → generate a design → add, rotate, save and reload furniture → open
  the catalogue/product page, send **Ask shop owner**, and verify the message on
  `/my/enquiries`.
- The temporary click-through account, design, enquiry and uploaded files were
  removed; the pre-existing data counts were unchanged.

## Screenshots

Generated by `tests/browser_check.py` (and `tests/placement_check.py` for the
rotated item) into `docs/screenshots/`:

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
| Custom area drag-select | ![Custom area](docs/screenshots/14-custom-area.png) |
| Paint area freehand strokes | ![Paint area](docs/screenshots/14-painted-area.png) |
| Product moderation | ![Moderation](docs/screenshots/15-product-moderation.png) |
| My enquiries | ![My enquiries](docs/screenshots/16-my-enquiries.png) |
| Rotated placement | ![Rotated placement](docs/screenshots/17-result-rotated.png) |

Six-step PDF walkthrough (screenshots 18–23 show the customer journey; 24–26 the
other roles):

| Step / role | Preview |
| --- | --- |
| 1 · Customer login | ![Login](docs/screenshots/18-step1-login.png) |
| 2 · Room upload | ![Upload](docs/screenshots/19-step2-upload.png) |
| 3 · CV measurement | ![Measurement](docs/screenshots/20-step3-measurement.png) |
| 4 · Design generation | ![Result](docs/screenshots/21-step4-result.png) |
| 5 · Furniture placement | ![Furniture](docs/screenshots/22-step5-placement.png) |
| 6 · Product + shop | ![Shop](docs/screenshots/23-step6-product.png) |
| Admin walkthrough | ![Admin](docs/screenshots/24-admin-walkthrough.png) |
| Designer walkthrough | ![Designer](docs/screenshots/25-designer-walkthrough.png) |
| Shop owner walkthrough | ![Shop owner](docs/screenshots/26-shop-owner-walkthrough.png) |

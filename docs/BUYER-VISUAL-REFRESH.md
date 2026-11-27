# Buyer visual refresh — 2026-11-26

Scope: buyer page `src/xborder_insight/commerce_shop_v2.html`. Seller and backend files unchanged.

Implemented the approved light-gray/white/deep-navy brand tokens; translucent sticky navigation; local product search; collection hero; truthful US shipping/demo-payment information; square explicitly labeled photo placeholders; responsive product cards; sticky desktop cart; mobile amount and checkout anchor; account and order presentation; keyboard focus and reduced-motion support.

Preservation check: all original business script lines remain identical, excluding `renderCatalog` presentation. Added only a read-only cart presentation observer; search is local and uses existing catalog data. All original static DOM IDs are preserved and unique, and HTML nesting passes. API calls, request parameters, session state, generation guards, operation locks, checkout keys, payment-result handling and seller link remain unchanged. No new dependencies or external assets. No invented ratings, discounts, variants, currency switching or product-detail routes.

Validation: targeted buyer/payment/identity/UI regression suite passed (24 tests); existing Starlette/httpx deprecation warning. Isolated headless Chrome at 1440x1000, 390x844 and 320x740 passed overflow, search, category filter, sold-out controls, cart badge/amount, checkout-anchor and sign-out reset checks. Preview API uses synthetic fixtures and rejects writes; no business database accessed. Expected anonymous account/me 401 responses are recorded separately from unexpected browser errors. Browser evidence and source snapshot: `D:/Codex_Projects/tmp/buyer-design/`.

No deployment or full project suite claimed. Product photos and richer commerce fields remain dependent on future data support.

## Category placeholders — 2026-11-26

Buyer `renderProductPlaceholder(product)` now renders six abstract category pictograms (air purifier, coffee machine, kettle, pet fountain, robot vacuum, wireless charger) with a generic parcel fallback, escaped Unicode-aware product initials and an always-visible `Sample / Placeholder` label. The pictograms indicate categories, not product appearance or specifications. Missing titles fall back to CB. Unknown and prototype-like category keys safely fall back to the parcel.

Only media-region styles, media contents/accessible label and the helper were changed. Exact source comparison against the immediate pre-change snapshot confirms the remaining business script and the product-body fields/actions are unchanged. Existing card/media/body hierarchy is retained. No API, backend, static route or database changes; no ratings, discounts, original prices or specifications added. Inline SVG uses no external image, font or resource references, so there is no image-loading failure state.

Validation: 24 targeted buyer/payment/identity/UI tests passed, with the existing Starlette/httpx warning. Helper checks cover six distinct illustrations, unknown/prototype keys, empty titles, Unicode and escaping. Isolated Chrome checks at 1440x1100, 390x844 and 320x740 verified placeholder labels fit inside their media containers, no horizontal overflow, no img/image/script nodes inside cards, and preserved search/category/sold-out/cart/sign-out behavior. Synthetic fixtures only; no business writes. Three expected anonymous account/me 401 responses, no unexpected browser errors. Evidence: `D:/Codex_Projects/tmp/buyer-design/placeholder-browser-check.json`; previews: `placeholder-desktop.png`, `placeholder-mobile.png`, `placeholder-small.png`. No deployment claimed.

## Local product reference images — 2026-11-26

Five downloaded, visually inspected reference photos are now stored locally as 1200 × 1200 WebP files. The first Pexels air-purifier candidate was rejected because visual inspection showed a projector. The replacement is an Unsplash category reference. No suitable licensed, subject-focused pet-fountain photograph was found; the three pet-fountain demo products share an original detailed SVG category illustration. The other six products use five photos (two robot-vacuum demo products share one).

Photos are labeled “Category reference / 品类参考图”; illustrations are labeled “Category illustration / 品类示意图” and include the existing product name. They do not assert exact SKU appearance, brand, material, capacity, performance or other specifications.

Static directory: `src/xborder_insight/static/product-images/`. FastAPI mount: `/commerce-assets/product-images/`. Product API/schema/database unchanged. The original catalog filtering, product-body markup, prices, quantities, inventory controls and all session/payment/business functions compare exactly with the pre-change source (apart from media accessibility text). Existing layout and card styling retained; added CSS is confined to media content. Photo files are selected by the existing category ID.

The inline category illustration remains visible until a photo has loaded successfully. Network/decode errors remove the img element and restore the illustration/title/reference label, without another image request or retry loop. Unknown categories use a detailed parcel illustration. No ratings, sales counts, discounts, promotional badges, original prices or extra specification fields were added.

### Product image mapping

| Product | Local file | Content |
|---|---|---|
| SIM / Acceptance robot_vacuum b2d7e6de | `robot-vacuum.webp` | White round robot vacuum on a tiled floor. |
| SIM / Acceptance pet_fountain b2d7e6de | `pet_fountain-illustration.svg` | Original category illustration: water reservoir, drinking tray, spout and visible stream; existing product name shown in the media region. Not a product photograph or specification. |
| DEMO / Robot vacuum | `robot-vacuum.webp` | White round robot vacuum on a tiled floor. |
| DEMO / Compact air purifier | `air-purifier.webp` | White cylindrical air purifier with top outlet and lower intake grille on a pale yellow background. |
| DEMO / Semi-automatic coffee machine | `espresso-machine.webp` | Countertop espresso machine with portafilter and cup. |
| DEMO / Electric kettle | `electric-kettle.webp` | Glass electric kettle, black handle, spout and power base. |
| DEMO / Wireless charger | `wireless-charger.webp` | Phone lying on a round wireless charging pad. |
| DEMO / Easy-clean fountain | `pet_fountain-illustration.svg` | Original category illustration: water reservoir, drinking tray, spout and visible stream; existing product name shown in the media region. Not a product photograph or specification. |
| DEMO / Quiet fountain | `pet_fountain-illustration.svg` | Original category illustration: water reservoir, drinking tray, spout and visible stream; existing product name shown in the media region. Not a product photograph or specification. |

### Sources and license

The downloadable provenance manifest is `src/xborder_insight/static/product-images/sources.json`: individual source pages, authors, license links, download URLs, transformations, checksums and product IDs.
- `robot-vacuum.webp`: [MART PRODUCTION](https://www.pexels.com/photo/white-round-robot-vacuum-on-gray-tiled-floor-7641488/), [Pexels License](https://www.pexels.com/license/); cropped/resized/padded as recorded in the manifest.
- `espresso-machine.webp`: [Kostiantyn Klymovets](https://www.pexels.com/photo/an-espresso-machine-on-a-kitchen-counter-13096241/), [Pexels License](https://www.pexels.com/license/); cropped/resized/padded as recorded in the manifest.
- `electric-kettle.webp`: [Engin Akyurt](https://www.pexels.com/photo/electric-glass-kettle-with-water-10965749/), [Pexels License](https://www.pexels.com/license/); cropped/resized/padded as recorded in the manifest.
- `wireless-charger.webp`: [Rann Vijay](https://www.pexels.com/photo/smartphone-charging-on-wireless-charger-7742584/), [Pexels License](https://www.pexels.com/license/); cropped/resized/padded as recorded in the manifest.
- `air-purifier.webp`: [VBreathe / enviroguardprox](https://unsplash.com/photos/a-white-cylindrical-object-with-a-black-top-and-bottom-M4OilrUTWyc), [Unsplash License](https://unsplash.com/license); cropped/resized/padded as recorded in the manifest.

### Validation and local deployment

- 24 buyer/payment/identity/UI regression tests passed; one existing Starlette/httpx deprecation warning.
- Dedicated static HTTP check: 13 local files returned 200 with byte-for-byte contents and expected image MIME types; missing files and traversal rejected with 404; no DB calls.
- Isolated FastAPI and actual local 8031 headless Chrome checks at desktop (1440 × 1100), mobile (390 × 844) and small mobile (320 × 740): six decoded photo cards, three illustration cards, visible labels, no horizontal overflow, search preserved, error recovery and blocked-photo network fallback passed. No external photo requests in the browser. Expected anonymous-account 401 responses only; no unexpected browser errors.
- Rebuilt the local Docker image and updated the existing loopback service, preserving the data volume. No seed/smoke transaction scripts were run. Pre/post database content hashes match. Deployed page matches source and every asset returns 200.
- Evidence and screenshots: `reports/buyer-product-images-20261126/`. No cloud deployment or live model calls.

## Pet-fountain photo and fixture display-title correction — 2026-11-26

The three pet-fountain cards now use `pet-fountain.webp`: a real indoor electric pet fountain with its reservoir, basin, flowing water and a drinking cat visible. Source: April Killingsworth, https://commons.wikimedia.org/wiki/File:Cat_fountain.jpg, CC BY 2.0 (https://creativecommons.org/licenses/by/2.0/). Cropped, padded to square, resized and converted to WebP. The original is 720 x 480; no claim of additional photographic detail. The former illustrative fallback remains available only for image failure. A visually inspected Unsplash candidate showing a street cat was rejected.

Photo credit/source/license/change notices are in the locally served `credits.html`, linked from the photo-reference caption; the source manifest is updated. No photographer or brand endorsement is implied; these remain category references for simulated products, not exact SKU photographs.

Two narrowly scoped aliases match both the known product ID and exact original title: `05707c8e013d40cea9fd01eea77486f5` → `SIM / Robot vacuum`; `84afb5a680d448bc890b3e5795141b64` → `SIM / Pet fountain`. Applied to catalog title/tooltip, accessibility text, media fallback title and current cart display. Search includes the clean display name. The simulation designation remains visible. Unknown products and seller-renamed titles pass through unchanged. Database titles, immutable historical order snapshots and API responses remain unchanged; no broad suffix stripping.

Validation: 24 buyer/payment/identity/UI regression tests passed, one existing Starlette/httpx warning; alias tests confirm exact matching, unknown/prototype keys, unchanged seller-renamed titles and no object mutation. Source comparison confirms identity/API/payment/order-snapshot functions remain unchanged. Isolated and actual 8031 headless Chrome at 1440 x 1100, 390 x 844, 320 x 740: all nine cards decode local real reference images; clean names visible; search, captions, no horizontal overflow, simulated error and blocked-image fallback passed. All 15 static files including credits returned 200. Rebuilt and updated the local Docker image/service; no seed/transaction scripts. Pre/post database content hashes match. Evidence: `reports/buyer-product-images-correction-20261126/`.

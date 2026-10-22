# CHECKLIST

An item is ticked only when a test or a recorded run proves it. Evidence is given in brackets.
Abbreviations: `core/` = `tests/core/`, `svc/` = `tests/services/`, `ui/` = `tests/ui/`, `shots` =
`docs/screenshots/NN_*.png` produced by `python store.py screenshots`.

## Rules & infrastructure
- [x] Local only; no git remotes, CI files or cloud services (project tree)
- [x] Every secret / URL / credential in `.env`, documented in `config/.env.example` (`config/loader.py` is the only reader)
- [x] Business values in `config/*.yaml` / `theme.json` (no-hard-coding sweep done; see README §4)
- [x] Roles defined once (`backend/shared/roles.py`); statuses + transitions defined once (`backend/shared/order_states.py`) [core/test_state_machine.py::test_transition_table_is_complete]
- [x] One CLI `store.py setup|seed|train|api|jobs|ui|test` (+ `screenshots`) — every command run in this environment
- [x] PostgreSQL only, no SQLite fallback (`config/settings.py`; `setup` exits if DB unreachable)
- [x] Docker Compose file provided (`docker-compose.yml`) — **written, not executed here (no Docker daemon)**
- [ ] Verified on Windows and macOS — not available in this environment (Linux only)

## Backend — folder one (core)
- [x] Schema + migrations applied to PostgreSQL 16 (`manage.py migrate`)
- [x] Faker seed command, size and seed from config (`store.py seed --reset`: 60 products, 600 customers, ~30k orders) [svc/test_end_to_end_ai.py]
- [x] Registration, login, Argon2 hashing [core/test_auth.py::test_register_creates_customer_with_argon2_hash]
- [x] Roles Customer/Staff/Admin; role checks on every endpoint [core/test_auth.py::test_every_api_endpoint_requires_authentication, ::test_role_checks]
- [x] Login rate limiting [core/test_auth.py::test_login_rate_limited]
- [x] Profiles & addresses (private per user) [core/test_auth.py::test_addresses_are_private; shot 15]
- [x] Catalog with categories, SKUs, images, search/filter/pagination [core/test_catalog_inventory.py]
- [x] Soft delete + restore [core/test_catalog_inventory.py::test_soft_delete_and_restore]
- [x] Inventory adjustments with movement log, no negative stock [core/test_catalog_inventory.py::test_stock_adjustment]
- [x] Persistent cart with server-side pricing [core/test_cart_checkout.py::test_cart_prices_on_server]
- [x] Reservation with expiry from config; lazy expiry on read; job release [core/test_cart_checkout.py::test_reservation_holds_stock_and_expires; svc/test_assistant_snapcheck_jobs.py::test_jobs_release_and_notify]
- [x] Atomic checkout: row locks, re-pricing, price snapshot [core/test_cart_checkout.py::test_checkout_creates_paid_order_with_price_snapshot]
- [x] Idempotent checkout and payments; idempotency-key conflict → 422 [core/test_cart_checkout.py::test_checkout_is_idempotent, ::test_declined_payment_then_retry_with_new_key]
- [x] Simulated gateway (success / declined / insufficient funds tokens) [same]
- [x] Order state machine with full status history; invalid moves rejected [core/test_state_machine.py::test_full_lifecycle_with_return_and_restock]
- [x] Cancellations (restock + refund) and returns (restock + refund) [core/test_state_machine.py]
- [x] **Concurrency: 100 simultaneous buyers, 10 units → exactly 10 orders** [core/test_concurrency.py]
- [x] Checkout hooks resolved by dotted path; folder one ships stubs [svc/test_discounts.py::test_hooks_resolve_to_folder_two; core tests use the stubs]

## Backend — folder two (services & AI)
- [x] Reports: order history, sales by period & category, low stock, customers; CSV + PDF [svc/test_risk_reviews_reports.py::test_reports_and_exports]
- [x] Discount rule engine (rules as data, codes + automatic, validation) [svc/test_discounts.py::test_code_and_automatic_rules, ::test_rule_validation_and_approval_flow]
- [x] Discount suggestions: slow movers, elasticity from past promotions, min-margin floor, DRAFT → Admin approve/reject [svc/test_discounts.py::test_slow_mover_suggestion_respects_min_margin; shot 30]
- [x] Reviews API, verified purchase, duplicates rejected, moderation [svc/test_risk_reviews_reports.py::test_reviews_verified_duplicates_and_moderation]
- [x] Review intelligence: sentiment model, fake heuristics, pros/cons [REPORT.md; shot 04, 29]
- [x] Fraud score 0–100 on every order; MEDIUM → OTP; HIGH → ON_HOLD [core/test_cart_checkout.py::test_high_risk_goes_on_hold_and_medium_requires_otp; svc/test_risk_reviews_reports.py::test_checkout_with_real_hook_sets_on_hold; shot 23]
- [x] Demand forecasting (horizon from config, 14–30) and restock (ROP formula) [svc/test_risk_reviews_reports.py::test_restock_formula; svc/test_end_to_end_ai.py; shot 21]
- [x] Segmentation RFM + K-Means into loyal / big spenders / new / at risk [svc/test_end_to_end_ai.py; shot 20]
- [x] SnapCheck: MATCH vs MISMATCH, mismatches fast-tracked to staff; photo search [svc/test_assistant_snapcheck_jobs.py::test_snapcheck_match_mismatch_and_photo_search; shots 05, 11, 12, 25]
- [ ] SnapCheck with pretrained CLIP — **not downloadable here**; fallback embedding used and stated (README §6, REPORT.md)
- [x] Hybrid recommendations with reason string [svc/test_end_to_end_ai.py]
- [x] Assistant: tools run with user's permissions; data-changing actions need confirmation [svc/test_assistant_snapcheck_jobs.py::test_local_assistant_search_and_confirmed_add, ::test_cancelled_action_never_runs; shot 14]
- [x] NL analytics mapped to whitelisted reports, role-checked [svc/test_assistant_snapcheck_jobs.py::test_analytics_whitelisted_and_role_checked; shot 19]
- [x] Fallback to locally trained intent classifier when no key [same tests; REPORT.md]
- [ ] LLM tool-calling path executed against the API — **no key available**; implemented in `assistant/engine.py::_llm`
- [x] Background jobs: reservation cleanup, notifications, nightly training (APScheduler) [`store.py jobs` ran interval jobs; `store.py jobs --once nightly_training` SUCCEEDED; svc/test_assistant_snapcheck_jobs.py::test_jobs_release_and_notify]

## AI training
- [x] Synthetic data with learnable structure + noise, all parameters in `config/ml.yaml`, seeded
- [x] Every model trained; joblib + metadata JSON (date, data hash, params, metrics) [ai/models/*_meta.json]
- [x] `ai/models/REPORT.md` written; states that metrics are synthetic
- [x] Baselines: forecasting WAPE/MAPE vs moving average (best per product by backtest); fraud precision within review budget; recs Precision@K/NDCG vs popularity; sentiment accuracy/F1; segmentation silhouette [REPORT.md]
- [x] `store.py train` retrains everything; nightly job calls the same `ai.train.train_all` [svc/test_end_to_end_ai.py; jobs run]

## UI — folder A (shell)
- [x] Storefront header (customers) and Seller Hub sidebar (staff), both from the registry; cards, rounded corners, light/dark toggle [shots 03, 17, 18; ui/test_ui.py::test_storefront_header_for_customers_and_sidebar_for_staff]
- [x] Palette/fonts from `config/theme.json` → generated stylesheet [ui/test_ui.py::test_theme_builds_both_modes]
- [x] Colour-coded status chips with sentence-case labels [shots 10, 23; ui/test_ui.py::test_status_labels_are_sentence_case]
- [x] Empty / loading / error states [shots 06 (empty), 32 (error); `StatePane` on every page]
- [x] API client: base URL config, token storage, auth header, 401 → login [shot 33]
- [x] QThread worker with loading indicator (`worker.py`, `Spinner`)
- [x] Base widgets: sortable paginated table, validated form, confirm dialog, error message [ui/test_ui.py::test_validated_form_and_table; shot 27]
- [x] Login / registration / profile / addresses [shots 01, 02, 15]
- [x] Role-based menu [ui/test_ui.py::test_role_based_menus]
- [x] Logout and session expiry [shot 33]
- [x] Catalog search, filters, search by photo [shots 03, 05]
- [x] Product page with reviews [shot 04]
- [x] Cart with server-calculated totals and discount code [shot 07]
- [x] Checkout: address, sandbox payment, COD, reservation countdown [shots 08, 09]
- [x] Clear out-of-stock and expired-reservation messages (`CheckoutDialog`, `CartPage`; API codes tested in core)
- [x] Order history with status timeline [shot 10]
- [x] SnapCheck upload [shots 11, 12]
- [x] Staff product form with validation + stock adjustment [shots 26, 27, 28]
- [x] Order queue: only valid transitions offered (next steps from the state machine); ON_HOLD flagged with risk score and reasons [shots 23, 24]

## UI — folder B (panels)
- [x] Panels register into the sidebar without editing the main window [ui/test_ui.py::test_folder_b_panels_register_without_main_window_changes]
- [x] User & role management [shot 31]
- [x] Discount manager (approve/reject drafts) [shot 30]
- [x] Sales dashboard charts + CSV/PDF export [shot 18; export endpoints tested in svc]
- [x] Review moderation [shot 29]
- [x] Customer segments + restock views [shots 20, 21]
- [x] Assistant chat with confirm click [shot 14]
- [x] NL analytics box [shot 19]
- [x] AI insights panel [shot 22]

## Verification
- [x] Tests pass: 55 passed (`python store.py test`)
- [x] API smoke test over HTTP (login, catalog, recommendations, assistant, analytics, restock, suggestions, segments, PDF)
- [x] Headless screenshots of every screen in `docs/screenshots/` (33), inspected and layout issues fixed
- [x] Mock mode (`UI_MOCK_MODE=true`) replays recorded fixtures with the API offline [ui/test_ui.py::test_mock_mode_replays_recorded_fixtures + offline run]

## Redesign and Indian data (follow-up request)
- [x] UI designed in Figma first: design system + catalogue, product, checkout, your orders, Seller Hub dashboard and orders [Figma file linked in README §7, checked with Figma screenshots]
- [x] PySide6 UI restyled to the design (tokens in `config/theme.json`), shorter copy, no clutter subtitles, text-only buttons [shots 01–33]
- [x] Money in ₹ with Indian grouping, dates in IST like "21 Oct 2026" [core/test_india_locale.py::test_indian_money_and_number_formatting, ::test_dates_use_store_time_zone]
- [x] PDF exports print ₹ (DejaVu Sans embedded) [manual export check]
- [x] Synthetic customers: Indian names, real localities with matching PIN codes and states, valid +91 mobiles [core/test_india_locale.py::test_generated_customers_have_valid_indian_addresses]
- [x] Indian catalogue, prices ending in 9, festive calendar, UPI / card / net banking / COD [config/categories.yaml, ml.yaml, business.yaml; seed + train run]
- [x] Address API validates PIN code, state and mobile for Indian addresses [core/test_auth.py::test_addresses_are_private]
- [x] Assistant understands ₹ amounts ("earbuds under ₹2,000") [svc/test_assistant_snapcheck_jobs.py::test_local_assistant_search_and_confirmed_add]

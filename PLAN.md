# PLAN — Online Store Database

## Environment findings (build machine)
- Python 3.13, PostgreSQL 16 server installed locally (no Docker daemon) → develop against local Postgres; ship `docker-compose.yml` for others.
- Hugging Face / OpenAI CDN are blocked → CLIP weights cannot be downloaded here. SnapCheck code tries CLIP (optional `requirements-clip.txt`) and falls back to a lightweight, documented image-embedding (colour histogram + gradient-orientation histogram + tiny thumbnail). The fallback is reported in the API response, the UI and REPORT.md.
- No LLM API key → assistant/analytics run on the locally trained intent classifier; the Anthropic tool-calling path activates when `LLM_API_KEY` is set.

## Phases
1. **Plan** — this file, CHECKLIST.md, config skeleton, `store.py` CLI.
2. **Core backend (folder_one_core)** — settings from `.env` + `config/*.yaml`; apps: accounts, catalog, inventory, cart, reservations, orders, payments; `shared/` hooks + roles + order state machine; seed command; tests incl. 100-buyers concurrency test. Smoke: `store.py setup && seed && api`, hit endpoints.
3. **Services (folder_two_services)** — reports (CSV/PDF), discounts (rules-as-data + suggestions + approval), reviews (+ intelligence), risk (score + OTP + ON_HOLD), forecasting/restock, segmentation, recommendations, SnapCheck, assistant + NL analytics, APScheduler jobs. Tests + smoke.
4. **AI training (ai/)** — synthetic generators driven by `config/ml.yaml`; train + backtest vs baselines; joblib + metadata JSON; `ai/models/REPORT.md`. Nightly job calls same `ai.train.train_all()`.
5. **UI** — folder_a_shell (shell, API client, QThread worker, base widgets, customer/staff screens), folder_b_panels (self-registering admin/AI panels); theme.json → QSS; offscreen screenshots of every screen into `docs/screenshots/`, inspect, fix.
6. **Docs** — README (Win/macOS/Linux), assumptions, summary of what works / what does not; CHECKLIST ticked only from test/run evidence.

## Key design decisions
- `backend/shared/roles.py` and `backend/shared/order_states.py` are the single declarative definitions of roles and status transitions.
- Checkout hooks resolved by dotted path from `config/business.yaml` (`checkout.hooks.apply_discounts`, `checkout.hooks.score_order`); folder one ships safe stubs in `shared/hooks.py`.
- Concurrency: `select_for_update()` on inventory rows ordered by product id, inside `transaction.atomic()`; availability = on_hand − active unexpired reservations (computed under the lock).
- All business values come from `config/business.yaml`, `config/ml.yaml`, `config/theme.json`, `.env`.

## Status (end of build)
All six phases done. Evidence lives in CHECKLIST.md (each tick cites a test or a run), the
model results in ai/models/REPORT.md, and the screens in docs/screenshots/. Open items: CLIP and the
LLM path could not be exercised here (blocked downloads / no key), Docker Compose and
Windows/macOS were not run (see README §9).

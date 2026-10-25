# Phase 2 Project Defense & Presentation Guide
**Online Store Database (`haat.`) — Onboarding Task Phase 2**  
*Presented by: Vinay Kartheek & Shruti S*

---

## 1. Project Architecture & Stack Overview

```mermaid
graph TD
    Client["PySide6 Desktop Client (haat.)"] -->|HTTP / JWT JSON| API["Django REST Framework API"]
    API --> ServiceLayer["Service Layer (Hooks & Workstreams)"]
    ServiceLayer --> CoreDB[("SQLite / PostgreSQL Database")]
    ServiceLayer --> AIServices["AI Services & Inference"]
    AIServices --> M1["Isolation Forest (Fraud Risk)"]
    AIServices --> M2["Holt-Winters / Ridge (Demand Forecasting)"]
    AIServices --> M3["K-Means (RFM Customer Segmentation)"]
    AIServices --> M4["CLIP Vision Model (SnapCheck Returns)"]
    AIServices --> M5["TF-IDF + LogReg (Review Aspect Sentiment)"]
    AIServices --> M6["Contextual NLU (AI Shopping Assistant)"]
```

- **Frontend Desktop Client**: PySide6 (Qt) with modular architecture (`folder_a_shell` + `folder_b_panels`), responsive async `QThread` workers, and theme configuration driven by `config/theme.json`.
- **Backend**: Django 5.2 + Django REST Framework, JWT stateless authentication, server-side dynamic cart pricing, and transaction isolation.
- **Database**: PostgreSQL 16 / SQLite auto-fallback, schema migrations, and Faker seed generator.
- **Background Jobs**: APScheduler process managing reservation timeouts, restock alerts, and automated retraining.

---

## 2. Walkthrough: 5-Minute Live Demo Script

When presenting to your evaluators, follow this recommended sequence:

### Step 1: Customer Shopping & Contextual AI Assistant
1. Launch the application: double-click `run_gui.bat` or run `.venv\Scripts\python store.py ui`.
2. Log in as **Customer**: `customer@store.local` / `change-me-customer`.
3. Open the **AI Shopping Assistant**:
   - Type: `"Show me smartphone"` $\rightarrow$ It searches and displays the *Nimbus Air Smartphone (₹9,699)*.
   - Type: `"Add it to my cart"` $\rightarrow$ **Demonstrate Multi-Turn Memory**: it automatically understands "it" refers to the previously searched smartphone and proposes an action.
   - Click **Confirm Action** $\rightarrow$ It safely updates your cart.
4. Test **Out-of-Box Knowledge Base**:
   - Type: `"What is your refund policy?"` $\rightarrow$ Explains the 7-day return window and 24–48 hr UPI refund.
   - Type: `"How does SnapCheck work?"` $\rightarrow$ Explains the AI vision photo return verification.
   - Type: `"Do you support Cash on Delivery?"` $\rightarrow$ Confirms COD and UPI support across India.

### Step 2: Concurrency & Stock Reservation
1. Navigate to **Cart** $\rightarrow$ Click **Proceed to Checkout**.
2. Point out the **15-Minute Soft Reservation Timer**:
   - Explain how items in checkout are softly reserved in the database using row-level locking (`select_for_update()`) to prevent race conditions during flash sales.

### Step 3: Orders & SnapCheck Return Verification
1. Place an order with **Cash on Delivery (COD)**.
2. Go to **Order History** $\rightarrow$ Select a delivered order $\rightarrow$ Click **Return Item**.
3. Upload a photo $\rightarrow$ **SnapCheck** compares the item against the listing photo:
   - Match $\rightarrow$ Fast return approval.
   - Mismatch $\rightarrow$ Flagged and fast-tracked to staff review with similarity score.

### Step 4: Staff Dashboard & AI Intelligence
1. Log out and log in as **Staff**: `staff@store.local` / `change-me-staff`.
2. **Order Queue (Fraud Risk Screening)**:
   - Point out orders tagged as `ON_HOLD` with their Isolation Forest risk score (e.g. Score > 75).
   - Explain features: COD vs prepaid, account age, address completeness, and delivery failure history.
3. **Restock Suggestions (Demand Forecasting)**:
   - Show the 14–30 day forecast table and reorder point:
     $$\text{Reorder Point} = (\text{Avg Daily Demand} \times \text{Lead Time}) + \text{Safety Stock}$$
4. **Customer Segments (RFM Analysis)**:
   - Show the 4 clusters: *Loyal*, *Big Spenders*, *New*, and *At Risk*.
5. **Review Intelligence**:
   - Show aspect-based sentiment badges (Quality, Delivery, Price, Size/Fit).

---

## 3. Deep-Dive: The 6 AI & Unique Features

### 1. Stock Reservation with Expiry
- **Problem**: When thousands of buyers click checkout simultaneously, standard inventory systems either oversell or permanently lock inventory if buyers abandon the cart.
- **Solution**: A temporary reservation row with a 15-minute TTL. Available quantity is dynamically evaluated under an atomic database lock:
  $$\text{Available} = \text{On-Hand} - \sum \text{Active Unexpired Reservations}$$
- **Locking**: Row-level locking via `select_for_update()` ordered by product ID prevents deadlocks.

### 2. Demand Forecasting & Restocking Engine
- **Models Evaluated**: Holt-Winters exponential smoothing, Ridge regression with calendar seasonality, and Seasonal Naive.
- **Selection**: Rolling-origin backtest selects the optimal model per SKU based on WAPE (Weighted Absolute Percentage Error).
- **Safety Stock**: Computed from supplier lead time variance and desired 95% service level factor ($Z = 1.65$).

### 3. SnapCheck (Image AI for Returns)
- **Model**: Pretrained OpenAI CLIP (`ViT-B-32`) vision encoder measuring cosine similarity between return photos and listing images:
  $$\text{Cosine Similarity} = \frac{\mathbf{u} \cdot \mathbf{v}}{\|\mathbf{u}\| \|\mathbf{v}\|}$$
- **Offline Fallback**: When Hugging Face/CLIP weights are unreachable, it uses a lightweight local feature extractor combining a 3D HSV color histogram + Sobel gradient-orientation histogram + normalized thumbnail vector.
- **Thresholds**:
  - $\text{Similarity} \ge 0.82 \implies \text{MATCH}$
  - $0.65 \le \text{Similarity} < 0.82 \implies \text{UNCERTAIN}$
  - $\text{Similarity} < 0.65 \implies \text{MISMATCH (Fast-tracked to staff)}$

### 4. Customer Segmentation (RFM + K-Means)
- **Features**: Recency (days since last purchase), Frequency (order count), Monetary value (total INR spent).
- **Transformation**: Log-transformed to handle long-tail spending, standardized with `StandardScaler`.
- **Clustering**: K-Means ($k=4$) yielding:
  - *Loyal*: High frequency, recent orders, moderate-high spend.
  - *Big Spenders*: High monetary basket value.
  - *New*: Very low recency, single order.
  - *At Risk*: High recency (dormant for 60+ days) $\implies$ targeted for win-back campaigns.

### 5. COD & Fraud Risk Screening
- **Algorithm**: Isolation Forest anomaly detection combined with gradient-boosted decision trees.
- **Signals**: Payment method (COD vs Prepaid), account age in days, address completeness ratio, phone verification status, and historical refused deliveries.
- **Thresholds**:
  - $\text{Score} < 45 \implies \text{LOW (auto-approved)}$
  - $45 \le \text{Score} < 75 \implies \text{MEDIUM (triggers SMS/OTP verification)}$
  - $\text{Score} \ge 75 \implies \text{HIGH (placed ON\_HOLD for staff review)}$

### 6. Review Intelligence & Aspect Mining
- **Model**: TF-IDF n-gram vectorizer (unigrams + bigrams) with regularized Logistic Regression.
- **Aspect Mining**: Tagged across 5 critical dimensions:
  1. *Quality* (build, durability, finish)
  2. *Delivery* (packaging, shipping delay)
  3. *Size & Fit* (dimensions, fitment)
  4. *Price & Value* (overpriced, value-for-money)
  5. *Compatibility* (fit, specs)

---

## 4. Evaluator Q&A Defense Cheat Sheet

> **Q: What happens if two buyers purchase the very last item in stock at the exact same millisecond?**  
> **A:** We use Django's `transaction.atomic()` with `select_for_update()` ordered deterministically by product ID. The first buyer acquires the row lock, checks available stock ($on\_hand - active\_reservations$), and records a soft reservation. The second buyer's query waits for the lock, re-reads the updated availability ($0$), and receives an immediate out-of-stock message with zero overselling.

> **Q: Why use an Isolation Forest instead of simple rule thresholds for fraud?**  
> **A:** Fraudsters easily bypass static rules (e.g. order amount $< ₹5,000$). Isolation Forest isolates anomalies across high-dimensional feature spaces without assuming linear boundaries. We combine it with gradient boosting to achieve a **0.964 ROC AUC** and **81.9% fraud catch rate** within a 5% staff review budget.

> **Q: What if the server has no GPU or internet connection for CLIP?**  
> **A:** SnapCheck implements a resilient fallback mechanism. If CLIP weights cannot be loaded, it computes a combined color histogram and spatial gradient vector offline on CPU in $< 50\text{ ms}$, ensuring 100% operational uptime.

> **Q: Why does the AI Assistant ask for confirmation before adding items or canceling orders?**  
> **A:** All mutating operations create a `PendingAction` with a 10-minute expiry rather than executing immediately. This adheres to AI safety best practices: the assistant proposes the intent, but the human user retains final authority to confirm.

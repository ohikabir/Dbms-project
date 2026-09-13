# SupplyNext Postman Collection

44 saved requests covering the whole API — the Spring backend and the Python ML
service — replacing the ad-hoc per-request testing this project used before.

## Import

1. Postman → **Import** → select both files:
   - `SupplyNext.postman_collection.json`
   - `SupplyNext.postman_environment.json`
2. Pick **SupplyNext - Local** from the environment dropdown (top right).

## Use

1. Run **1. Auth → Register (ADMIN)** once, to create a user.
2. Run **1. Auth → Login**.

That second request has a test script that writes the JWT into the `token`
environment variable. The collection sets bearer auth from `{{token}}` at the
top level, so **every other request inherits it automatically** — no copying
tokens between tabs.

Then work top to bottom: warehouses and categories first, then suppliers,
products, inventory, and finally orders. Folder numbering follows the
dependency order.

## Variables

| Variable | Default | |
|---|---|---|
| `baseUrl` | `http://localhost:8080` | Spring backend |
| `mlUrl` | `http://localhost:8000` | Python ML service |
| `token` | *(empty)* | Set automatically by Login |
| `role` | *(empty)* | Set automatically by Login |

Point `baseUrl` at a deployed instance to run the same collection against it.

## Notes

- Every list endpoint is paginated — `?page=0&size=10`.
- Analytics only counts **SHIPPED** sales orders as demand, so ship a few
  orders before expecting meaningful EOQ or forecast numbers.
- EOQ returns "missing cost data" until `unitCost`, `holdingCostRate` and
  `orderingCost` are set on the product (folder 5 has a PATCH for that).
- Safety stock and reorder point need the supplier's `leadTimeDays`
  (folder 4 has a PATCH for that).
- Folder 12 targets `{{mlUrl}}`, not the backend, and those requests are
  unauthenticated because the ML service currently has no auth.
- A few requests are deliberately *expected to fail* — "Adjust stock (reject
  negative)" and "Create transfer (same warehouse)" both assert that the
  backend's guards actually work.

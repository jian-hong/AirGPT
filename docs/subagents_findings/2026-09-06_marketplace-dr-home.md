keywords: [marketplace, DR-0007, catalog, serving, plane-1, env.local, constructor]
main_idea: Marketplace DR lives in AirGPT as DR-0007 proposed. Catalog+fit here; bind_serve is a recipe not a pid; OpenVault owns local ground models.

# Marketplace DR home

AirGPT `docs/decisions/DR-0007-marketplace-is-catalog-not-serving.md`.
Not OpenVault (PRODUCT_ROLES already owns local models) and not Netie
(no sixth file type). Confirmation: `tests/test_marketplace_roles.py`.

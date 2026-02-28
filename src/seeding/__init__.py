"""Test data seeding module for AumOS integration tests.

Provides idempotent seed data creation for:
- 3 test tenants (Alpha, Beta, Gamma)
- 5 users per tenant (one per privilege level 1-5)
- Stable UUIDs for reproducibility across runs

Usage:
    # From Python (e.g. in a conftest.py fixture):
    from src.seeding.seed import seed_all
    await seed_all(engine)

    # From shell (via scripts/seed-test-data.sh):
    python -m src.seeding.seed
"""

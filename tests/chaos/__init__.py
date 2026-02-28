"""Chaos and fault-injection tests for AumOS resilience verification.

These tests deliberately introduce failures to verify that the resilience
layer (circuit breakers, retries, fail-open patterns) behaves correctly
under real failure conditions.

All tests require AUMOS_USE_TESTCONTAINERS=true and Docker socket access.
"""

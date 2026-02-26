# Changelog

All notable changes to aumos-integration-tests will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial scaffolding with full infrastructure stack via docker-compose
- Phase 0 skeleton tests: tenant isolation, auth flow, event propagation, RLS enforcement
- Phase 1 skeleton tests: synthesis pipeline
- Phase 2 skeleton tests: governance flow
- Smoke tests: service health endpoint verification
- Fixtures: Keycloak realm config, sample tabular and text data
- Scripts: wait-for-services, seed-test-data

# Changelog

All notable changes to `household-finance-kit` will be documented in this file.

The format is based on Keep a Changelog, and this project is expected to use semantic versioning once releases begin.

## [Unreleased]

### Added

- Established M0 Foundations for the public toolkit: approved design brief, top-level documentation, repository skeleton, package layout, CLI stubs, example configuration files, bucket presets, and a small pytest suite.
- Added public-repo safety infrastructure: `scripts/privacy_scan.py`, the Tiller read-only guard hook at `hooks/tiller_guard.py`, and CI coverage for tests and privacy checks.
- Recorded the two-repo model that keeps this public toolkit separate from private household instances containing workbooks, generated reports, and local financial decisions.

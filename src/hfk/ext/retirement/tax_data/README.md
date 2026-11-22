# Federal tax tables

This folder holds the versioned federal tax tables for the retirement extension,
one file per tax year, named `us-federal-<tax year>.yaml`. The format is described
in `hfk/ext/retirement/tax.py`.

Rules for adding a table:

- Every figure must come from an official IRS or SSA publication. Name the
  publication and section in `source` (and in `social_security.source`).
- Never copy figures from memory, a news story, or another tool.
- Give `social_security` a `base` and `adjusted_base` for every filing status the
  table lists under `filing_status`; a missing one is an error naming the key.
- A figure you cannot verify is left out. hfk then fails loudly; it never guesses.
- The maintainer checks each new table against its publication before release.
- Add a year's table once that year has started. The extension uses the newest
  table and treats its figures as the current year's dollars, so a table for a
  later year would put brackets and thresholds a year of inflation ahead.

`us-federal-2026.yaml` holds the 2026 figures from IRS Rev. Proc. 2025-32 and
IRS Publication 915 (2026), retrieved from irs.gov on 2026-11-22. The 2027 figures
are in IRS Rev. Proc. 2026-35; add `us-federal-2027.yaml` from it in January 2027.

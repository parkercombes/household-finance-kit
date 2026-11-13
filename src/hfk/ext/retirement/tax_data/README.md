# Federal tax tables

This folder holds the versioned federal tax tables for the retirement extension,
one file per tax year, named `us-federal-<tax year>.yaml`. The format is described
in `hfk/ext/retirement/tax.py`.

Rules for adding a table:

- Every figure must come from an official IRS or SSA publication. Name the
  publication and section in `source` (and in `social_security.source`).
- Never copy figures from memory, a news story, or another tool.
- A figure you cannot verify is left out. hfk then fails loudly; it never guesses.
- The maintainer checks each new table against its publication before release.

No table ships yet: the 2026 figures could not be read from irs.gov when M8-04 was
built, so the extension stops with "no federal tax table is installed" until the
maintainer adds one.

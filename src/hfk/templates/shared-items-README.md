# Shared items

This folder holds shared costs that are not in your Tiller workbook, for the
settle-up extension. Use it only if `settle_up` is listed under `extensions`
in `household.yaml` and your household has exactly two people.

Write one file per month, named `YYYY-MM.yaml`, such as `2026-08.yaml`:

    schema_version: 1
    items:
      - label: "Example utility bill"
        amount: 120.00
        paid_by: alex
        weights: {alex: 0.5, sam: 0.5}
        bucket: "Fixed Essential"

Each item needs a `label`, a positive `amount`, who paid it (`paid_by`), how
it is shared (`weights`, which sum to exactly 1), and a `bucket` from
`declarations.yaml`. A month with no file has no shared items.
`hfk doctor` checks every file here.

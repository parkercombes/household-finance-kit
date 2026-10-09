# Example Instance

This directory is a complete private-instance shape using only the example files.
The `data/` directory is gitignored and absent.

To run doctor by hand:

```bash
hfk dev fixture --out examples/instance/data/Tiller-Example.xlsx
hfk doctor --home examples/instance --today 2026-10-01
```

Delete `examples/instance/data/` afterwards. `scripts/privacy_scan.py` blocks workbook
files anywhere in the tree.

Automated acceptance is
`tests/test_doctor.py::test_example_instance_passes_doctor`, which does the same work in
a temporary directory.

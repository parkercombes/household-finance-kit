"""The shipped federal tax table matches its IRS publications (M8-04).

The figures below are the ones printed in the publications the table cites, not
values worked out from the table, so a mistyped bracket or deduction fails here.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from hfk.ext.retirement.tax import (
    bracket_tax,
    federal_income_tax,
    newest_federal_table,
    taxable_social_security,
)

D = Decimal

# IRS Rev. Proc. 2025-32, section 3.01: "Over X ... the tax is $Y plus ..." for each
# bracket of Table 1 (married filing jointly) and Table 3 (unmarried individuals).
REV_PROC_2025_32_TAX_AT_BRACKET_START = {
    "married_joint": {
        24800: D("2480"),
        100800: D("11600"),
        211400: D("35932"),
        403550: D("82048"),
        512450: D("116896"),
        768700: D("206583.50"),
    },
    "single": {
        12400: D("1240"),
        50400: D("5800"),
        105700: D("17966"),
        201775: D("41024"),
        256225: D("58448"),
        640600: D("192979.25"),
    },
}


def test_the_shipped_table_is_2026_and_names_its_sources() -> None:
    table = newest_federal_table()
    assert table.tax_year == 2026
    assert "Rev. Proc. 2025-32" in table.source
    assert "Publication 915 (2026)" in table.social_security.source


@pytest.mark.parametrize("status", ["married_joint", "single"])
def test_brackets_reproduce_the_rev_proc_tax_amounts(status: str) -> None:
    brackets = newest_federal_table().status(status).brackets
    for start, tax in REV_PROC_2025_32_TAX_AT_BRACKET_START[status].items():
        assert bracket_tax(D(start), brackets) == tax, (status, start)


def test_standard_deductions_match_rev_proc_section_3_14() -> None:
    table = newest_federal_table()
    assert table.status("married_joint").standard_deduction == D("32200")
    assert table.status("single").standard_deduction == D("16100")
    # 100,000 of income filing jointly: 67,800 taxable, 2,480 + 12% of 43,000.
    assert federal_income_tax(D("100000"), table, "married_joint") == D("7640.00")


def test_social_security_reproduces_publication_915_worksheet_1() -> None:
    rule = newest_federal_table().social_security
    assert rule.for_status("married_joint") == (D("32000"), D("44000"))
    assert rule.for_status("single") == (D("25000"), D("34000"))
    # Publication 915 (2026), the filled-in Worksheet 1 for a single filer: benefits
    # of 5,980 (line 1) and line 8 of 31,980, so other income is 31,980 - 2,990.
    # The taxable part is 2,990 (line 19).
    assert taxable_social_security(D("5980"), D("28990"), rule, "single") == D("2990.00")

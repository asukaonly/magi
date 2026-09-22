"""A scalar has one host identity and an independently preserved source span."""

import pytest

from magi.memory.l2.literal_grounding import canonical_literal_value, grounded_literal_surface


@pytest.mark.parametrize(("predicate", "value", "source", "surface", "canonical"), [
    ("BIRTH_DATE", "1992年9月8日", "我出生于1992年9月8日", "1992年9月8日", "1992-09-08"),
    ("BIRTH_DATE", "一九九二年九月八日", "生日：1992-09-08", "1992-09-08", "1992-09-08"),
    ("BIRTH_DATE", "09-08", "生日是９月８日", "９月８日", "09-08"),
    ("BIRTH_DATE", "2月29日", "生日是二月二十九日", "二月二十九日", "02-29"),
    ("STATED_AGE", "三十", "我今年30岁", "30", 30),
    ("STATED_AGE", "30", "我今年三十岁", "三十", 30),
    ("STATED_AGE", "二十八", "我已经二十八岁了", "二十八", 28),
    ("STATED_AGE", "102", "我今年一百零二岁", "一百零二", 102),
    ("STATED_AGE", "130", "年龄：一百三十", "一百三十", 130),
    ("STATED_AGE", "0", "现在零岁", "零", 0),
    ("BIRTH_YEAR", "二千零二十四", "出生年份是二〇二四", "二〇二四", 2024),
    ("BIRTH_YEAR", "1992", "生于一千九百九十二年", "一千九百九十二", 1992),
])
def test_source_and_candidate_share_typed_scalar_identity(predicate, value, source, surface, canonical):
    assert canonical_literal_value(predicate, value) == canonical
    assert grounded_literal_surface(predicate, value, [source]) == surface
    assert canonical_literal_value(predicate, surface) == canonical


@pytest.mark.parametrize(("predicate", "value", "source"), [
    ("BIRTH_DATE", "1992-09-08", "出生于1993年9月8日"),
    ("BIRTH_DATE", "1992-09-08", "生日是九月八日"),
    ("BIRTH_DATE", "09-08", "出生于1992年9月8日"),
    ("BIRTH_DATE", "1993年2月29日", "出生于1993年2月29日"),
    ("BIRTH_DATE", "二零二四年十三月三日", "二零二四年十三月三日"),
    ("STATED_AGE", "30", "我今年一百三十岁"),
    ("STATED_AGE", "三十", "我今年三十一岁"),
    ("STATED_AGE", "30", "另一个数字是-30"),
    ("STATED_AGE", "30", "数字是30.5"),
    ("STATED_AGE", "30", "数字是三十点五"),
    ("STATED_AGE", "130", "我今年一百三岁"),
    ("STATED_AGE", "131", "年龄是一百三十一"),
    ("STATED_AGE", "三十三十", "年龄是三十三十"),
    ("BIRTH_YEAR", "1992", "数字是一九九二零"),
    ("REAL_NAME", "王小明", "我喜欢苹果"),
    ("PLANS_TO", "去海边休假一周", "我计划去海边"),
])
def test_scalar_normalization_never_invents_missing_evidence(predicate, value, source):
    assert grounded_literal_surface(predicate, value, [source]) is None

"""Pure-SQL sampling builders — shape checks (no DB)."""

from __future__ import annotations

import pytest

from app.db.schema_ddl import _sample_chosen_ids_sql, _sample_insert_sql


def test_random_picks_distinct_ids_in_random_order():
    sql = _sample_chosen_ids_sql(7, 1000, "random")
    assert "DISTINCT EVENT_ID" in sql
    assert "RANDOM()" in sql
    assert "ORDER BY r" in sql
    assert "rn <= 1000" in sql
    assert "PROJECT_ID = 7" in sql
    # No bucketing machinery on the random path.
    assert "LISTAGG" not in sql and "GREATEST" not in sql


def test_temporal_is_proportional_with_clean_random_cap():
    sql = _sample_chosen_ids_sql(3, 500, "temporal")
    assert "TO_CHAR(MIN(EVENT_TIME), 'YYYY-MM')" in sql
    assert "GREATEST(1, ROUND(sz.cnt / tot.total * 500))" in sql
    # Clean proportional: the global cap trims in random order, not bucket order.
    assert "ORDER BY r) AS grn" in sql
    assert "ORDER BY bucket" not in sql
    assert "grn <= 500" in sql


def test_path_diverse_buckets_on_the_step_sequence_hash():
    sql = _sample_chosen_ids_sql(9, 250, "pathDiverse")
    assert "LISTAGG(CAST(STEP_ID AS VARCHAR(20)), '>')" in sql
    assert "HASH_MD5(" in sql
    assert "GREATEST(1, ROUND(sz.cnt / tot.total * 250))" in sql
    assert "ORDER BY r) AS grn" in sql


def test_unknown_method_rejected():
    with pytest.raises(ValueError):
        _sample_chosen_ids_sql(1, 10, "bogus")


def test_insert_copies_original_rows_under_the_slot_label():
    sql = _sample_insert_sql(42, 100, "random", "SAMPLE_2")
    assert "INSERT INTO JOURNEYS" in sql
    assert "'SAMPLE_2'" in sql
    # Only ORIGINAL rows are the source, and the pick is a semi-join subquery.
    assert "(j.SAMPLE_SET = 'ORIGINAL' OR j.SAMPLE_SET IS NULL)" in sql
    assert "j.EVENT_ID IN (" in sql
    assert "PROJECT_ID = 42" in sql

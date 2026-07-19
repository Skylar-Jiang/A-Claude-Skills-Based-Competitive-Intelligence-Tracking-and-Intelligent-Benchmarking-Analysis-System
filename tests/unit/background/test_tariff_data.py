import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

from app.background.tariff_data import build_tariff_database, parse_us_hts_table, write_normalized_jsonl


def test_tariff_import_cli_help_runs_from_repository_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/import_us_hts_tariffs.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--database-output" in result.stdout


def test_parse_us_hts_table_and_build_serving_db(tmp_path: Path) -> None:
    source = tmp_path / "us_hts_sample.csv"
    source.write_text(
        "\n".join(
            [
                "HTS Number,Article Description,General,Special,Other,Effective Date,Expiration Date,HTS Version",
                "8421.21.0000,Filtering or purifying machinery for liquids,Free,,25%,2026-01-01,,2026 Rev. 11",
                "4201.00.6000,Dog collars and similar animal gear,2.4%,A*,,2026-01-01,2026-12-31,2026 Rev. 11",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    records = parse_us_hts_table(source)

    assert [record.hs_code for record in records] == ["8421210000", "4201006000"]
    assert records[0].general_rate == "Free"
    assert records[1].special_rate_text == "A*"
    assert records[1].end_date == date(2026, 12, 31)

    normalized_output = tmp_path / "normalized" / "us_hts_tariffs.jsonl"
    database_output = tmp_path / "serving" / "tariff_rules.sqlite"
    write_normalized_jsonl(records, normalized_output)
    build_tariff_database(records, database_output, metadata={"source_file": source.name})

    assert normalized_output.read_text(encoding="utf-8").count("\n") == 2
    with sqlite3.connect(database_output) as connection:
        rule_count = connection.execute("SELECT COUNT(*) FROM tariff_rules").fetchone()[0]
        source_file = connection.execute(
            "SELECT value FROM import_metadata WHERE key = 'source_file'"
        ).fetchone()[0]

    assert rule_count == 2
    assert source_file == "us_hts_sample.csv"

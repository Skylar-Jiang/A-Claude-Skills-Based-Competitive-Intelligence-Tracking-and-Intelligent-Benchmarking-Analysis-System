import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.catalog_type_inventory import (  # noqa: E402
    CatalogTypeRow,
    build_catalog_type_inventory,
    classify_catalog_type,
)

TYPE_FLAG_SCHEMA_VERSION = "1"
TYPE_CLASSIFIER_VERSION = "source-leaf-v1"


def audit_catalog(catalog_path: Path, *, example_limit: int = 3) -> dict[str, object]:
    uri = f"file:{catalog_path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM catalog_meta"))
        inventory = build_catalog_type_inventory(
            _catalog_rows(connection),
            example_limit=example_limit,
        )
    return {
        "inventory_version": 1,
        "classifier_version": TYPE_CLASSIFIER_VERSION,
        "taxonomy_basis": "source_leaf_with_generic_parent_disambiguation",
        "catalog_signature": metadata.get("source_signature", ""),
        "catalog_schema_version": metadata.get("schema_version", ""),
        "classification_boundary": (
            "Offline source-derived product-type candidates only; not global labels or peer-match gates."
        ),
        "inventory": asdict(inventory),
    }


def render_inventory_markdown(result: dict[str, object]) -> str:
    inventory = result["inventory"]
    types = inventory["types"]
    lines = [
        "# 商品目录终端类型盘点",
        "",
        "> 本结果是来源推导的类型候选，不是线上硬分类，也不保证每个类型都有评论数据。",
        "",
        f"- 商品总数：{inventory['total_product_count']}",
        f"- 已写入类型标志：{inventory['assigned_product_count']}",
        f"- 类型桶数量：{inventory['type_count']}",
        f"- 缺失来源类别、仍待解析的商品数：{inventory['unresolved_product_count']}",
        f"- 商品目录签名：`{result['catalog_signature']}`",
        "",
        "| 类型名称 | 稳定键 | 商品数 | 状态 |",
        "| --- | --- | ---: | --- |",
    ]
    for item in types:
        label = str(item["type_label"]).replace("|", "\\|")
        status = "待解析" if item["unresolved"] else "来源类别"
        lines.append(f"| {label} | `{item['type_key']}` | {item['product_count']} | {status} |")
    lines.append("")
    return "\n".join(lines)


def build_type_flag_cache(catalog_path: Path, cache_path: Path) -> dict[str, int | bool]:
    catalog_uri = f"file:{catalog_path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(catalog_uri, uri=True)) as catalog:
        metadata = dict(catalog.execute("SELECT key, value FROM catalog_meta"))
        source_signature = metadata.get("source_signature", "")
        catalog_schema_version = metadata.get("schema_version", "")
        existing = _existing_cache_summary(
            cache_path,
            source_signature=source_signature,
            catalog_schema_version=catalog_schema_version,
        )
        if existing is not None:
            return {"rebuilt": False, **existing}

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
        temporary.unlink(missing_ok=True)
        with closing(sqlite3.connect(temporary)) as target:
            target.executescript(
                """
                CREATE TABLE type_flag_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE product_type_flags (
                    parent_asin TEXT PRIMARY KEY,
                    type_key TEXT NOT NULL,
                    type_label TEXT NOT NULL,
                    source_category_path TEXT NOT NULL,
                    classification_method TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    unresolved INTEGER NOT NULL CHECK (unresolved IN (0, 1))
                );
                CREATE INDEX ix_product_type_flags_type_key ON product_type_flags(type_key);
                """
            )
            for parent_asin, _title, categories_json in catalog.execute(
                "SELECT parent_asin, title, categories_json FROM catalog_products ORDER BY parent_asin"
            ):
                assignment = classify_catalog_type(
                    [str(value) for value in json.loads(categories_json or "[]")]
                )
                target.execute(
                    "INSERT INTO product_type_flags VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        parent_asin,
                        assignment.type_key,
                        assignment.type_label,
                        assignment.source_category_path,
                        assignment.classification_method,
                        assignment.confidence,
                        int(assignment.unresolved),
                    ),
                )
            row_count, unresolved_count, type_count = target.execute(
                "SELECT COUNT(*), SUM(unresolved), COUNT(DISTINCT type_key) FROM product_type_flags"
            ).fetchone()
            target.executemany(
                "INSERT INTO type_flag_meta VALUES (?, ?)",
                [
                    ("schema_version", TYPE_FLAG_SCHEMA_VERSION),
                    ("classifier_version", TYPE_CLASSIFIER_VERSION),
                    ("catalog_source_signature", source_signature),
                    ("catalog_schema_version", catalog_schema_version),
                    ("row_count", str(row_count)),
                    ("unresolved_count", str(unresolved_count or 0)),
                    ("type_count", str(type_count)),
                ],
            )
            target.commit()
        os.replace(temporary, cache_path)
    return {
        "rebuilt": True,
        "row_count": int(row_count),
        "unresolved_count": int(unresolved_count or 0),
        "type_count": int(type_count),
    }


def _existing_cache_summary(
    cache_path: Path,
    *,
    source_signature: str,
    catalog_schema_version: str,
) -> dict[str, int] | None:
    if not cache_path.exists():
        return None
    try:
        uri = f"file:{cache_path.resolve().as_posix()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            metadata = dict(connection.execute("SELECT key, value FROM type_flag_meta"))
            if (
                metadata.get("schema_version") != TYPE_FLAG_SCHEMA_VERSION
                or metadata.get("classifier_version") != TYPE_CLASSIFIER_VERSION
                or metadata.get("catalog_source_signature") != source_signature
                or metadata.get("catalog_schema_version") != catalog_schema_version
            ):
                return None
            actual_count = connection.execute("SELECT COUNT(*) FROM product_type_flags").fetchone()[0]
            if actual_count != int(metadata.get("row_count", "-1")):
                return None
            return {
                "row_count": actual_count,
                "unresolved_count": int(metadata.get("unresolved_count", "0")),
                "type_count": int(metadata.get("type_count", "0")),
            }
    except (sqlite3.DatabaseError, ValueError):
        return None


def _catalog_rows(connection: sqlite3.Connection) -> Iterator[CatalogTypeRow]:
    for parent_asin, title, categories_json in connection.execute(
        "SELECT parent_asin, title, categories_json FROM catalog_products ORDER BY parent_asin"
    ):
        categories = json.loads(categories_json or "[]")
        yield CatalogTypeRow(
            parent_asin=str(parent_asin),
            title=str(title),
            categories=[str(value) for value in categories],
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit source-derived concrete product-type candidates for every catalog row.",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("data/demo/cache/product_catalog.sqlite"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/demo/validation/terminal_product_type_inventory.json"),
    )
    parser.add_argument(
        "--flag-cache",
        type=Path,
        default=Path("data/demo/cache/product_type_flags.sqlite"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("data/demo/validation/terminal_product_type_inventory.md"),
    )
    parser.add_argument("--example-limit", type=int, default=3)
    return parser


def main() -> None:
    args = _parser().parse_args()
    result = audit_catalog(args.catalog, example_limit=args.example_limit)
    cache_summary = build_type_flag_cache(args.catalog, args.flag_cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_inventory_markdown(result), encoding="utf-8")
    inventory = result["inventory"]
    print(
        json.dumps(
            {
                "catalog_signature": result["catalog_signature"],
                "total_product_count": inventory["total_product_count"],
                "assigned_product_count": inventory["assigned_product_count"],
                "type_count": inventory["type_count"],
                "unresolved_product_count": inventory["unresolved_product_count"],
                "type_flag_cache": str(args.flag_cache),
                "type_flag_cache_rebuilt": cache_summary["rebuilt"],
                "output": str(args.output),
                "markdown_output": str(args.markdown_output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

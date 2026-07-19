import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the TradePilot real-mode HTTP acceptance flow.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/demo/validation/real_http_e2e.json"),
    )
    return parser


def _data(response: httpx.Response) -> object:
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise AssertionError(payload)
    return payload["data"]


def run(args: argparse.Namespace) -> dict[str, object]:
    started = time.perf_counter()
    with httpx.Client(base_url=args.base_url, timeout=180, trust_env=False) as client:
        health = _data(client.get("/api/v1/health"))
        workflow_contract = _data(client.get("/api/v1/workflow/metadata"))
        product = _data(
            client.post(
                "/api/v1/products",
                json={
                    "name": "Cordless 3L Stainless Steel Cat Water Fountain",
                    "category": "pet water fountain",
                    "description": (
                        "Unlisted complete cordless drinking fountain for cats with a stainless steel basin, "
                        "rechargeable circulation system, removable reservoir, and visible water level."
                    ),
                    "attributes": {
                        "Target Species": "Cat",
                        "Product Type": "Pet Water Fountain",
                        "Capacity": "3L",
                    },
                    "features": [
                        "cordless rechargeable circulation",
                        "stainless steel drinking basin",
                        "removable reservoir",
                        "visible water level",
                    ],
                    "use_scenarios": ["indoor cat hydration without a nearby power outlet"],
                    "target_market": "United States",
                    "target_audience": ["indoor cat owners"],
                    "target_price": 39.99,
                    "target_currency": "USD",
                    "known_risks": ["pump noise validation", "battery endurance validation"],
                    "data_mode": "real",
                },
            )
        )
        assert product["data_origin"] == "user"
        created = client.post(
            "/api/v1/analysis-runs",
            json={
                "product_id": product["product_id"],
                "data_mode": "real",
                "target_market": "United States",
                "jurisdiction": "US",
                "platform": "Amazon",
                "background_context_types": ["tariff_rate"],
                "background_provider": "us-tariff-provider",
                "user_constraints": {
                    "new_product_has_own_reviews": False,
                    "new_product_has_own_sales": False,
                    "new_product_has_own_rating": False,
                },
            },
        )
        assert created.status_code == 202, created.text
        run_id = _data(created)["run_id"]
        deadline = time.monotonic() + args.timeout_seconds
        observed_nodes: set[str] = set()
        while time.monotonic() < deadline:
            status = _data(client.get(f"/api/v1/analysis-runs/{run_id}/status"))
            observed_nodes.add(str(status["current_node"]))
            if status["status"] in {"succeeded", "manual_review", "failed"}:
                break
            time.sleep(1)
        else:
            raise TimeoutError(f"run {run_id} did not finish")
        if status["status"] != "succeeded":
            raise AssertionError(status)

        run = _data(client.get(f"/api/v1/analysis-runs/{run_id}"))
        timeline = _data(client.get(f"/api/v1/analysis-runs/{run_id}/timeline"))
        agents = _data(client.get(f"/api/v1/analysis-runs/{run_id}/agents"))
        peers = _data(client.get(f"/api/v1/analysis-runs/{run_id}/peers"))
        evidence = _data(client.get(f"/api/v1/analysis-runs/{run_id}/evidence"))
        first_evidence_id = evidence["evidence"][0]["evidence_id"]
        evidence_detail = _data(
            client.get(f"/api/v1/analysis-runs/{run_id}/evidence/{first_evidence_id}")
        )
        audit = _data(client.get(f"/api/v1/analysis-runs/{run_id}/audit"))
        metadata = _data(client.get(f"/api/v1/analysis-runs/{run_id}/metadata"))
        report_id = run["report_id"]
        report = _data(client.get(f"/api/v1/reports/{report_id}"))
        markdown_response = client.get(f"/api/v1/reports/{report_id}/markdown")
        markdown_response.raise_for_status()
        markdown = markdown_response.text
        report_json = client.get(f"/api/v1/reports/{report_id}/json").json()
        events_text = client.get(f"/api/v1/analysis-runs/{run_id}/events").text
        event_ids = [int(value) for value in re.findall(r"^id: (\d+)$", events_text, re.MULTILINE)]
        reconnect_text = client.get(
            f"/api/v1/analysis-runs/{run_id}/events",
            headers={"Last-Event-ID": str(event_ids[0])},
        ).text
        replay_ids = [int(value) for value in re.findall(r"^id: (\d+)$", reconnect_text, re.MULTILINE)]
        support = _data(
            client.post(
                f"/api/v1/reports/{report_id}/support",
                json={
                    "action": "explain",
                    "section_id": "peer-market-product-analysis",
                    "message": "Explain this strategy, its evidence, and limitations.",
                },
            )
        )

    parent_asins = set(peers["selected_parent_asins"])
    evidence_ids = {item["evidence_id"] for item in evidence["evidence"]}
    review_evidence = [
        item for item in evidence["evidence"] if item["knowledge_type"] == "review_insight"
    ]
    assert 1 <= len(parent_asins) <= 30
    assert all(item["parent_asin"] in parent_asins for item in peers["peers"])
    assert all(item["metadata"]["parent_asin"] in parent_asins for item in review_evidence)
    assert all(item["metadata"]["evidence_scope"] == "peer_product" for item in review_evidence)
    assert all(item["metadata"]["peer_group_id"] == peers["peer_group_id"] for item in review_evidence)
    assert evidence_detail["evidence"]["evidence_id"] == first_evidence_id
    peer_titles = [str(item["title"]).casefold() for item in peers["peers"]]
    for accessory_phrase in ("replacement filter", "cat fountain filter", "cleaning kit"):
        assert all(accessory_phrase not in title for title in peer_titles)
    assert len(agents["agents"]) == 4
    assert all(item["real_model_called"] is True for item in agents["agents"])
    assert all(item["provider"] and item["model_name"] for item in agents["agents"])
    assert len(workflow_contract["nodes"]) == 8
    assert observed_nodes != {"product_preparation"}
    assert metadata["workflow_metadata"]["parallel_agent_overlap"] is True
    assert report["is_demo"] is False
    strategy = report["sections"]["launch_marketing_strategy"]
    assert strategy["marketing_objective"]
    assert strategy["target_segments"]
    assert strategy["value_propositions"]
    assert strategy["pricing_strategy"]
    assert strategy["channel_strategy"]
    assert strategy["messaging_strategy"]
    assert strategy["launch_actions"]
    assert report["sections"]["tax_and_tariff_snapshot"]["tariff_evidence"]
    assert report_json["report_id"] == report_id
    assert audit["audit"]["status"] in {"pass", "warning"}
    assert set(support["evidence_ids"]).issubset(evidence_ids)
    assert replay_ids == event_ids[1:]
    for forbidden in (
        "DEMO",
        "Scaffold",
        "当前商品用户反馈",
        "该商品用户普遍认为",
        "当前商品差评",
        "evidence_id",
        "证据ID",
        "待验证数值",
        "同类组：",
        "Configured Phase",
        "{'",
    ):
        assert forbidden not in markdown
    assert re.search(r"(?<![A-Z0-9])B0[A-Z0-9]{8}(?![A-Z0-9])", markdown) is None
    assert "同类市场商品分析" in markdown
    assert "同类市场用户洞察" in markdown
    assert "新商品上市营销策略" in markdown
    assert "分析范围：基于 Amazon 同类市场商品及其真实评论样本" in markdown
    assert "### 营销目标" in markdown
    assert "### 证据" in markdown
    assert "待验证假设" in markdown

    result = {
        "health": health,
        "workflow_node_count": len(workflow_contract["nodes"]),
        "observed_current_nodes": sorted(observed_nodes),
        "run_id": run_id,
        "report_id": report_id,
        "status": status["status"],
        "peer_group_id": peers["peer_group_id"],
        "peer_product_count": len(parent_asins),
        "review_evidence_count": len(review_evidence),
        "agent_count": len(agents["agents"]),
        "audit_status": audit["audit"]["status"],
        "parallel_agent_overlap": metadata["workflow_metadata"]["parallel_agent_overlap"],
        "event_count": len(event_ids),
        "replay_event_count": len(replay_ids),
        "support_evidence_count": len(support["evidence_ids"]),
        "stages": timeline["stages"],
        "agent_timings": [
            {
                "agent_name": item["agent_name"],
                "started_at": item["started_at"],
                "completed_at": item["completed_at"],
                "duration_ms": item["duration_ms"],
            }
            for item in agents["agents"]
        ],
        "workflow_metadata": metadata["workflow_metadata"],
        "peer_selection_metadata": metadata["peer_selection_metadata"],
        "total_http_e2e_duration_ms": round((time.perf_counter() - started) * 1000),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    try:
        result = run(_parser().parse_args())
    except Exception as exc:
        print(f"real HTTP E2E failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

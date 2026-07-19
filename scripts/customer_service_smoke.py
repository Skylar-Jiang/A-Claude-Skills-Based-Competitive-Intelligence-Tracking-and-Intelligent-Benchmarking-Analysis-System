import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def main() -> None:
    root = Path("data/demo/customer-service-smoke")
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{root / 'smoke.db'}",
        report_dir=root / "reports",
        upload_dir=root / "uploads",
        chroma_dir=root / "chroma",
    )
    with TestClient(create_app(settings)) as client:
        product = client.post(
            "/api/v1/products",
            json={"name": "Customer service smoke fixture", "category": "demo", "data_mode": "demo"},
        ).json()["data"]
        run = client.post(
            "/api/v1/analysis-runs",
            json={"product_id": product["product_id"], "data_mode": "demo"},
        ).json()["data"]
        report_id = None
        for _ in range(200):
            payload = client.get(f"/api/v1/analysis-runs/{run['run_id']}").json()["data"]
            report_id = payload.get("report_id")
            if report_id:
                break
            time.sleep(0.01)
        if not report_id:
            raise RuntimeError("Smoke report was not created")
        message = client.post(
            f"/api/v1/reports/{report_id}/customer-service/messages",
            json={
                "message": "如果目标用户调整为大学生群体，方案应该如何变化？",
                "personality": "professional",
            },
        ).json()["data"]
        conversation = client.get(
            f"/api/v1/reports/{message['report_id']}/customer-service/conversations/{message['conversation_id']}"
        ).json()["data"]
    print(
        json.dumps(
            {
                "report_id": message["report_id"],
                "report_version": message["report_version"],
                "conversation_id": message["conversation_id"],
                "action_taken": message["action_taken"],
                "changed_section_ids": message["changed_section_ids"],
                "confirmed_requirements": conversation["confirmed_requirements"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

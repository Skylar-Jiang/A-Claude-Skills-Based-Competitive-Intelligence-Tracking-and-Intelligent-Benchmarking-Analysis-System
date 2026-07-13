from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def success(request: Request, data: Any, *, status_code: int = 200, data_mode: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {
                "success": True,
                "data": data,
                "meta": {
                    "request_id": request.state.request_id,
                    "api_version": "v1",
                    "data_mode": data_mode,
                },
                "error": None,
            }
        ),
    )


def failure(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "data": None,
            "meta": {"request_id": request.state.request_id, "api_version": "v1", "data_mode": None},
            "error": {"code": code, "message": message, "details": details or []},
        },
    )

"""PetHospitalClient：参数转发、重试、错误分类、响应解析（全部 MockTransport）。"""

from __future__ import annotations

import httpx
import pytest

from conftest import SAMPLE_LIST_DATA, make_rest_client, ok_envelope

from pet_hospital_mcp.errors import BackendCallError, ErrorCode


async def aclose(client) -> None:
    await client.aclose()


async def test_list_pets_forwards_all_query_params_and_returns_data() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=ok_envelope(SAMPLE_LIST_DATA))

    client = make_rest_client(handler)
    try:
        data = await client.list_pets(
            {
                "q": "肠胃炎",
                "name": "旺财",
                "ownerName": "张三",
                "ownerPhone": "13900000000",
                "species": "犬",
                "doctor": "王医生",
                "disease": "肠胃炎",
                "status": "已康复",
                "min": 100,
                "max": 5000,
                "sortBy": "totalCost",
                "order": "desc",
                "page": 2,
                "pageSize": 50,
            }
        )
    finally:
        await aclose(client)

    assert captured["path"] == "/api/v1/pets"
    assert captured["params"] == {
        "q": "肠胃炎",
        "name": "旺财",
        "ownerName": "张三",
        "ownerPhone": "13900000000",
        "species": "犬",
        "doctor": "王医生",
        "disease": "肠胃炎",
        "status": "已康复",
        "min": "100",
        "max": "5000",
        "sortBy": "totalCost",
        "order": "desc",
        "page": "2",
        "pageSize": "50",
    }
    assert data == SAMPLE_LIST_DATA


async def test_none_params_are_dropped() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=ok_envelope(SAMPLE_LIST_DATA))

    client = make_rest_client(handler)
    try:
        await client.list_pets({"q": "旺财", "page": None, "pageSize": None})
    finally:
        await aclose(client)

    assert captured["params"] == {"q": "旺财"}


@pytest.mark.parametrize(
    ("status_code", "body", "expected_attempts"),
    [
        (400, {"code": 400, "message": "参数错误", "data": None}, 1),
        (404, {"code": 404, "message": "not found", "data": None}, 1),
        (500, {"code": 500, "message": "内部错误", "data": None}, 3),
    ],
)
async def test_http_error_responses_become_backend_api_error(
    status_code: int, body: dict, expected_attempts: int
) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status_code, json=body)

    client = make_rest_client(handler, max_retries=2)
    try:
        with pytest.raises(BackendCallError) as exc_info:
            await client.list_pets({"page": 1})
    finally:
        await aclose(client)

    err = exc_info.value
    assert err.code == ErrorCode.BACKEND_API_ERROR
    assert str(status_code) in err.message
    assert err.details["httpStatus"] == status_code
    # 4xx（429 除外）不重试；5xx 在有限次数内重试
    assert calls["n"] == expected_attempts


async def test_5xx_retried_then_success() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"code": 503, "message": "临时不可用"})
        return httpx.Response(200, json=ok_envelope(SAMPLE_LIST_DATA))

    client = make_rest_client(handler, max_retries=2)
    try:
        data = await client.list_pets({})
    finally:
        await aclose(client)

    assert calls["n"] == 3
    assert data == SAMPLE_LIST_DATA


async def test_timeout_after_retries_is_backend_timeout() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.TimeoutException("simulated timeout")

    client = make_rest_client(handler, max_retries=2)
    try:
        with pytest.raises(BackendCallError) as exc_info:
            await client.list_pets({})
    finally:
        await aclose(client)

    err = exc_info.value
    assert err.code == ErrorCode.BACKEND_TIMEOUT
    assert calls["n"] == 3
    # 不泄漏 httpx 异常类型名或内部细节
    assert "TimeoutException" not in err.message
    assert "httpx" not in err.message.lower()


async def test_connect_error_is_backend_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = make_rest_client(handler, max_retries=0)
    try:
        with pytest.raises(BackendCallError) as exc_info:
            await client.list_pets({})
    finally:
        await aclose(client)

    err = exc_info.value
    assert err.code == ErrorCode.BACKEND_UNAVAILABLE
    assert "ConnectError" not in err.message


async def test_non_json_body_is_backend_invalid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="oops not json", headers={"content-type": "text/plain"})

    client = make_rest_client(handler)
    try:
        with pytest.raises(BackendCallError) as exc_info:
            await client.list_pets({})
    finally:
        await aclose(client)

    assert exc_info.value.code == ErrorCode.BACKEND_INVALID_RESPONSE


async def test_missing_data_field_is_backend_invalid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 200, "message": "ok"})

    client = make_rest_client(handler)
    try:
        with pytest.raises(BackendCallError) as exc_info:
            await client.list_pets({})
    finally:
        await aclose(client)

    assert exc_info.value.code == ErrorCode.BACKEND_INVALID_RESPONSE


async def test_non_object_body_is_backend_invalid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    client = make_rest_client(handler)
    try:
        with pytest.raises(BackendCallError) as exc_info:
            await client.list_pets({})
    finally:
        await aclose(client)

    assert exc_info.value.code == ErrorCode.BACKEND_INVALID_RESPONSE


async def test_upstream_business_failure_code_is_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 50001, "message": "业务失败", "data": None})

    client = make_rest_client(handler)
    try:
        with pytest.raises(BackendCallError) as exc_info:
            await client.list_pets({})
    finally:
        await aclose(client)

    err = exc_info.value
    assert err.code == ErrorCode.BACKEND_API_ERROR
    assert err.details["upstreamCode"] == 50001

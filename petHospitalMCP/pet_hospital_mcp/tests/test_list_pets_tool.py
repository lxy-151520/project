"""list_pets 工具层：入参严格校验、成功归一化、错误信封映射。"""

from __future__ import annotations

import json
import math

import httpx
import pytest

from conftest import SAMPLE_LIST_DATA, make_rest_client, ok_envelope

from pet_hospital_mcp.tools.list_pets import TOOL_NAME, ListPetsInput, execute_list_pets


def _result_text(result) -> dict:
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    return json.loads(result.content[0].text)


async def test_success_normalizes_null_records_and_charges() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ok_envelope(SAMPLE_LIST_DATA))

    client = make_rest_client(handler)
    try:
        result = await execute_list_pets({}, client)
    finally:
        await client.aclose()

    assert result.is_error is not True
    payload = _result_text(result)
    assert set(payload.keys()) == {"items", "total", "page", "pageSize", "totalPages", "totalCost"}
    assert payload["total"] == 2
    items = payload["items"]
    # 数组保持原样
    assert isinstance(items[0]["records"], list) and len(items[0]["records"]) == 1
    assert isinstance(items[0]["charges"], list) and len(items[0]["charges"]) == 1
    # Go 给 null 时归一化为 []
    assert items[1]["records"] == []
    assert items[1]["charges"] == []


async def test_unknown_argument_is_validation_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("校验失败时不应调用上游")

    client = make_rest_client(handler)
    try:
        result = await execute_list_pets({"page": 1, "unexpectedParam": "x"}, client)
    finally:
        await client.aclose()

    assert result.is_error is True
    body = _result_text(result)
    assert body["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "arguments",
    [
        {"species": "狗"},               # 非枚举种类
        {"status": "康复"},               # 非枚举状态
        {"sortBy": "password"},           # 非排序字段
        {"order": "DESC"},                # 大小写非法
        {"page": 0},                      # 页码越界
        {"page": -3},
        {"pageSize": 0},
        {"pageSize": 501},                # 每页上限 500
        {"min": -0.01},                   # 花费不能为负
        {"max": -1},
        {"min": 1000, "max": 100},        # min > max
        {"page": "1"},                    # 数字字符串不隐式转换
        {"pageSize": True},               # bool 不能冒充整数
        {"q": ["肠胃炎"]},                # 类型错误
        {"name": 123},
        {"min": "100"},
        {"ownerName": "   "},             # 空白字符串
        {"min": math.nan},                # NaN 禁止
        {"max": math.inf},                # Infinity 禁止
    ],
)
async def test_invalid_arguments_all_return_validation_error(arguments: dict) -> None:
    client = make_rest_client(lambda request: httpx.Response(599))
    try:
        result = await execute_list_pets(arguments, client)
    finally:
        await client.aclose()

    assert result.is_error is True
    body = _result_text(result)
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["validationErrors"]


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"q": "肠胃炎"},
        {"species": "犬", "status": "就诊中"},
        {"min": 0, "max": 0},
        {"page": 1, "pageSize": 500},
        {"sortBy": "createdAt", "order": "asc"},
    ],
)
def test_valid_arguments_pass_pydantic(arguments: dict) -> None:
    parsed = ListPetsInput.model_validate(arguments)
    query = parsed.to_query()
    assert set(query).issubset(
        {
            "q", "name", "ownerName", "ownerPhone", "species", "doctor", "disease",
            "status", "min", "max", "sortBy", "order", "page", "pageSize",
        }
    )
    assert "page" not in query or query["page"] >= 1


def test_to_query_omits_none_and_keeps_camel_case() -> None:
    parsed = ListPetsInput.model_validate(
        {"ownerName": "张三", "ownerPhone": "13900000000", "pageSize": 20}
    )
    assert parsed.to_query() == {
        "ownerName": "张三",
        "ownerPhone": "13900000000",
        "pageSize": 20,
    }


async def test_backend_timeout_maps_to_error_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    client = make_rest_client(handler, max_retries=0)
    try:
        result = await execute_list_pets({"q": "x"}, client)
    finally:
        await client.aclose()

    assert result.is_error is True
    body = _result_text(result)
    assert body["error"]["code"] == "BACKEND_TIMEOUT"


async def test_backend_unavailable_maps_to_error_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = make_rest_client(handler, max_retries=0)
    try:
        result = await execute_list_pets({"q": "x"}, client)
    finally:
        await client.aclose()

    assert result.is_error is True
    assert _result_text(result)["error"]["code"] == "BACKEND_UNAVAILABLE"


async def test_data_shape_mismatch_is_backend_invalid_response() -> None:
    broken_data = dict(SAMPLE_LIST_DATA)
    del broken_data["totalPages"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ok_envelope(broken_data))

    client = make_rest_client(handler)
    try:
        result = await execute_list_pets({}, client)
    finally:
        await client.aclose()

    assert result.is_error is True
    assert _result_text(result)["error"]["code"] == "BACKEND_INVALID_RESPONSE"


async def test_unexpected_exception_becomes_internal_error_without_leakage() -> None:
    class ExplodingClient:
        async def list_pets(self, params):  # noqa: ANN001
            raise RuntimeError("super secret internal detail: boom")

    result = await execute_list_pets({}, ExplodingClient())  # type: ignore[arg-type]
    assert result.is_error is True
    body = _result_text(result)
    assert body["error"]["code"] == "INTERNAL_ERROR"
    serialized = json.dumps(body, ensure_ascii=False)
    assert "boom" not in serialized
    assert "RuntimeError" not in serialized


def test_tool_name_constant() -> None:
    assert TOOL_NAME == "list_pets"

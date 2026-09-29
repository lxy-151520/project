"""MCP 工具 ``list_pets`` —— 适配 Go REST API ``GET /api/v1/pets``。

本次阶段只实现这一个工具。输入、成功输出、错误输出均使用 Pydantic 建模；
工具失败统一返回 :data:`ErrorCode` 定义的结构化错误信封。
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Mapping
from typing import Any, Literal

from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ..errors import BackendCallError, ErrorCode, envelope_to_json, make_error_envelope
from ..logging_config import log_tool_event
from ..rest_client import PetHospitalClient

TOOL_NAME = "list_pets"

# ---- 与 Go 后端 /api/v1/meta 完全一致的真实允许值 -------------------------
SPECIES_VALUES = ("犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他")
STATUS_VALUES = ("待就诊", "就诊中", "住院中", "已康复", "慢性病随访")
SORT_BY_VALUES = (
    "id",
    "name",
    "ownerName",
    "species",
    "doctor",
    "disease",
    "status",
    "totalCost",
    "visitCount",
    "createdAt",
    "updatedAt",
)
ORDER_VALUES = ("asc", "desc")

Species = Literal[
    "犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"
]
VisitStatus = Literal["待就诊", "就诊中", "住院中", "已康复", "慢性病随访"]
SortField = Literal[
    "id",
    "name",
    "ownerName",
    "species",
    "doctor",
    "disease",
    "status",
    "totalCost",
    "visitCount",
    "createdAt",
    "updatedAt",
]
SortOrder = Literal["asc", "desc"]

_STRING_FIELDS = frozenset(
    {"q", "name", "ownerName", "ownerPhone", "species", "doctor", "disease", "status", "sortBy", "order"}
)
_INTEGER_FIELDS = frozenset({"page", "pageSize"})
_FLOAT_FIELDS = frozenset({"min", "max"})


class ListPetsInput(BaseModel):
    """``list_pets`` 入参，字段名与 Go 查询参数一一对应（camelCase）。"""

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, min_length=1)
    name: str | None = Field(default=None, min_length=1)
    ownerName: str | None = Field(default=None, min_length=1)
    ownerPhone: str | None = Field(default=None, min_length=1)
    species: Species | None = None
    doctor: str | None = Field(default=None, min_length=1)
    disease: str | None = Field(default=None, min_length=1)
    status: VisitStatus | None = None
    min: float | None = Field(default=None, ge=0)
    max: float | None = Field(default=None, ge=0)
    sortBy: SortField | None = None
    order: SortOrder | None = None
    page: int | None = Field(default=None, ge=1)
    pageSize: int | None = Field(default=None, ge=1, le=500)

    @model_validator(mode="before")
    @classmethod
    def _reject_bad_types_and_non_finite(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            raise ValueError("参数必须是 JSON 对象")
        for key, value in data.items():
            if value is None:
                continue
            if key in _STRING_FIELDS and not isinstance(value, str):
                raise ValueError(f"参数 {key} 必须是字符串")
            if key in _INTEGER_FIELDS:
                # bool 是 int 的子类，必须显式拒绝；数字字符串也不做隐式转换
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"参数 {key} 必须是整数")
            if key in _FLOAT_FIELDS:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"参数 {key} 必须是非负数字")
                if not math.isfinite(float(value)):
                    raise ValueError(f"参数 {key} 不能是 NaN 或 Infinity")
        return data

    @field_validator("q", "name", "ownerName", "ownerPhone", "doctor", "disease")
    @classmethod
    def _reject_blank(cls, value: str | None) -> str | None:
        if value is not None and value.strip() == "":
            raise ValueError("不能是空白字符串")
        return value

    @model_validator(mode="after")
    def _check_cost_range(self) -> "ListPetsInput":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min 不能大于 max")
        return self

    def to_query(self) -> dict[str, Any]:
        """转为转发给 Go 后端的查询参数（丢弃 None，键名保持 camelCase）。"""
        return self.model_dump(exclude_none=True, mode="json")


class PetSummary(BaseModel):
    """列表中的单只宠物摘要；只宽松建模已知字段，未知字段保留。"""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str | None = None
    species: str | None = None
    breed: str | None = None
    gender: str | None = None
    ageMonths: int | None = None
    color: str | None = None
    chipNo: str | None = None
    ownerName: str | None = None
    ownerPhone: str | None = None
    ownerAddr: str | None = None
    doctor: str | None = None
    disease: str | None = None
    status: str | None = None
    allergy: str | None = None
    note: str | None = None
    # Go 对无病历 / 无消费的新档案可能序列化出 null，这里统一归一化为 []
    records: list[dict[str, Any]] = Field(default_factory=list)
    charges: list[dict[str, Any]] = Field(default_factory=list)
    totalCost: float | None = None
    visitCount: int | None = None
    createdAt: str | None = None
    updatedAt: str | None = None

    @field_validator("records", "charges", mode="before")
    @classmethod
    def _null_becomes_empty_list(cls, value: Any) -> Any:
        return [] if value is None else value


class ListPetsData(BaseModel):
    """成功输出：对应 Go 成功响应信封中的 ``data``。"""

    model_config = ConfigDict(extra="ignore")

    items: list[PetSummary]
    total: int
    page: int
    pageSize: int
    totalPages: int
    totalCost: float


def error_result(code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> CallToolResult:
    """构造标记为失败的 2.x ``CallToolResult``，文本内容即统一错误信封 JSON。"""
    envelope = make_error_envelope(code, message, details)
    return CallToolResult(
        content=[TextContent(type="text", text=envelope_to_json(envelope))],
        is_error=True,
    )


def _validation_error_result(exc: ValidationError) -> CallToolResult:
    details = {
        "validationErrors": [
            {"loc": [str(part) for part in err["loc"]], "msg": err["msg"]}
            for err in exc.errors()
        ]
    }
    return error_result(
        ErrorCode.VALIDATION_ERROR,
        "list_pets 输入参数校验失败",
        details,
    )


async def execute_list_pets(arguments: Mapping[str, Any], client: PetHospitalClient) -> CallToolResult:
    """校验入参 -> 调用 Go API -> 校验/归一化响应，任何失败都返回统一错误信封。"""
    started = time.perf_counter()
    raw_params = dict(arguments)
    try:
        parsed_input = ListPetsInput.model_validate(arguments)
    except ValidationError as exc:
        result = _validation_error_result(exc)
        log_tool_event(
            tool_name=TOOL_NAME,
            params=raw_params,
            status="validation_error",
            duration_ms=(time.perf_counter() - started) * 1000,
            error_code=ErrorCode.VALIDATION_ERROR.value,
        )
        return result

    query = parsed_input.to_query()
    try:
        data = await client.list_pets(query)
    except BackendCallError as exc:
        result = error_result(exc.code, exc.message, exc.details)
        log_tool_event(
            tool_name=TOOL_NAME,
            params=raw_params,
            status="error",
            duration_ms=(time.perf_counter() - started) * 1000,
            error_code=exc.code.value,
        )
        return result
    except Exception:  # noqa: BLE001 - 兜底：任何意外都不向客户端泄漏内部堆栈
        log_tool_event(
            tool_name=TOOL_NAME,
            params=raw_params,
            status="error",
            duration_ms=(time.perf_counter() - started) * 1000,
            error_code=ErrorCode.INTERNAL_ERROR.value,
        )
        return error_result(
            ErrorCode.INTERNAL_ERROR,
            "list_pets 执行过程中发生内部错误",
        )

    try:
        success = ListPetsData.model_validate(data)
    except ValidationError as exc:
        locations = [
            ".".join(str(part) for part in err["loc"]) for err in exc.errors()
        ]
        result = error_result(
            ErrorCode.BACKEND_INVALID_RESPONSE,
            "宠物医院服务返回的数据不符合 list_pets 数据模型",
            {"invalidFields": locations[:20]},
        )
        log_tool_event(
            tool_name=TOOL_NAME,
            params=raw_params,
            status="error",
            duration_ms=(time.perf_counter() - started) * 1000,
            error_code=ErrorCode.BACKEND_INVALID_RESPONSE.value,
        )
        return result

    text = json.dumps(success.model_dump(mode="json"), ensure_ascii=False)
    log_tool_event(
        tool_name=TOOL_NAME,
        params=raw_params,
        status="ok",
        duration_ms=(time.perf_counter() - started) * 1000,
    )
    return CallToolResult(content=[TextContent(type="text", text=text)])


class ListPetsValidationMiddleware:
    """SDK 2.x ServerMiddleware：在 SDK 自身参数校验之前运行。

    作用：对 ``list_pets`` 的原始 arguments 做权威严格校验（拒绝未知字段、
    NaN/Infinity、错误类型、非法枚举与范围），保证所有非法输入都得到统一的
    ``VALIDATION_ERROR`` 信封，而不是 SDK 默认的自由文本错误。
    """

    async def __call__(self, ctx: Any, call_next: Any) -> Any:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        params = ctx.params
        if not isinstance(params, Mapping) or params.get("name") != TOOL_NAME:
            return await call_next(ctx)

        arguments = params.get("arguments")
        if arguments is not None and not isinstance(arguments, Mapping):
            return error_result(
                ErrorCode.VALIDATION_ERROR,
                "list_pets 输入参数校验失败",
                {"validationErrors": [{"loc": ["arguments"], "msg": "必须是 JSON 对象"}]},
            )

        try:
            ListPetsInput.model_validate(arguments or {})
        except ValidationError as exc:
            return _validation_error_result(exc)

        return await call_next(ctx)


def register_list_pets(server: Any, client: PetHospitalClient) -> None:
    """在 MCPServer 上注册 list_pets 工具。

    显式声明的签名同时决定发布给客户端的 JSON Schema（枚举、范围、类型）。
    """

    @server.tool(name=TOOL_NAME)
    async def list_pets(  # noqa: PLR0913
        q: str | None = None,
        name: str | None = None,
        ownerName: str | None = None,
        ownerPhone: str | None = None,
        species: Species | None = None,
        doctor: str | None = None,
        disease: str | None = None,
        status: VisitStatus | None = None,
        min: float | None = Field(default=None, ge=0),
        max: float | None = Field(default=None, ge=0),
        sortBy: SortField | None = None,
        order: SortOrder | None = None,
        page: int | None = Field(default=None, ge=1),
        pageSize: int | None = Field(default=None, ge=1, le=500),
    ) -> CallToolResult:
        """查询宠物医院的宠物档案列表（对应后端 GET /api/v1/pets）。

        用途：按关键词、主人、种类、医生、疾病、就诊状态、总花费区间过滤档案，
        并支持排序与分页。适用于"列出所有宠物 / 查某医生接诊的宠物 /
        按消费区间筛选 / 全文检索关键词"等场景。

        参数（全部可选，均与后端查询参数同名；非法值会返回 VALIDATION_ERROR）：
        - q: 全文检索关键词（跨字段，空格分词 AND，含病历内容）
        - name: 按宠物姓名过滤
        - ownerName: 按主人姓名过滤
        - ownerPhone: 按主人电话过滤
        - species: 种类，只能是 犬/猫/兔/鸟/仓鼠/爬宠/其他
        - doctor: 按主治医生姓名过滤
        - disease: 按疾病/诊断关键词过滤
        - status: 就诊状态，只能是 待就诊/就诊中/住院中/已康复/慢性病随访
        - min: 总花费下限（非负数）
        - max: 总花费上限（非负数，且 min <= max）
        - sortBy: 排序字段，可选 id/name/ownerName/species/doctor/disease/
          status/totalCost/visitCount/createdAt/updatedAt
        - order: 排序方向，asc 或 desc
        - page: 页码，从 1 开始
        - pageSize: 每页条数，1 到 500

        返回值（成功，JSON 文本，等价于后端信封的 data 字段）：
        {"items": [宠物档案...], "total": 总条数, "page": 当前页,
         "pageSize": 每页数, "totalPages": 总页数, "totalCost": 全部档案总花费}。
        每条档案的 records / charges 为数组（后端可能给 null，已归一化为 []）。

        失败时工具结果被标记为失败（isError=true），内容为统一错误信封：
        {"error": {"code": "...", "message": "...", "details": {}}}，
        code 取值：VALIDATION_ERROR / BACKEND_TIMEOUT / BACKEND_UNAVAILABLE /
        BACKEND_API_ERROR / BACKEND_INVALID_RESPONSE / INTERNAL_ERROR。
        """
        return await execute_list_pets(
            {
                "q": q,
                "name": name,
                "ownerName": ownerName,
                "ownerPhone": ownerPhone,
                "species": species,
                "doctor": doctor,
                "disease": disease,
                "status": status,
                "min": min,
                "max": max,
                "sortBy": sortBy,
                "order": order,
                "page": page,
                "pageSize": pageSize,
            },
            client,
        )

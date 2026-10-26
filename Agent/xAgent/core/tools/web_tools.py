# -*- coding: utf-8 -*-
"""网络工具: searchWeb (百度千帆搜索) + fetchWeb (curl + trafilatura 抓网页)。"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

try:
    import trafilatura
except ImportError:
    trafilatura = None


# ============================================================
# searchWeb —— 调用百度千帆 AI 搜索 API
# ============================================================

SEARCH_API_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"


def _get_search_api_key() -> str:
    """从 config.ini 的 [search] 段读取 API key,没有则返回空串。"""
    import configparser
    from pathlib import Path
    # 向上找到项目根 (xAgent/)
    root = Path(__file__).resolve().parents[3]  # tools/ -> core/ -> xAgent/
    ini = root / "config.ini"
    if not ini.exists():
        return ""
    cp = configparser.ConfigParser()
    cp.read(ini, encoding="utf-8")
    if "search" in cp:
        return cp["search"].get("baidu_qianfan_api_key", "").strip()
    return ""


def searchWeb(query: str, top_k: int = 8) -> str:
    """调用百度千帆 AI 搜索,返回精简的搜索结果列表。

    Args:
        query: 搜索关键词或问题,长度 <= 72 字符 (百度要求)。
        top_k: 返回结果条数,默认 8。

    Returns:
        格式化后的搜索结果字符串;失败时返回错误信息。
    """
    if requests is None:
        return "[searchWeb 不可用] 请先安装 requests: pip install requests"

    api_key = _get_search_api_key()
    if not api_key:
        return "[searchWeb 未配置] config.ini 的 [search] 段缺少 baidu_qianfan_api_key"

    if not query or not query.strip():
        return "[searchWeb 参数错误] query 不能为空"

    # 百度要求 query 长度 <= 72 字符
    query = query[:72]

    payload = {
        "messages": [{"role": "user", "content": query}],
        "search_source": "baidu_search_v2",
        "resource_type_filter": [{"type": "web", "top_k": min(top_k, 10)}],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            SEARCH_API_URL,
            headers=headers,
            data=json.dumps(payload),
            timeout=15,
        )
    except requests.exceptions.Timeout:
        return "[searchWeb 错误] 请求超时 (15s)"
    except requests.exceptions.ConnectionError as e:
        return f"[searchWeb 错误] 网络连接失败: {e}"
    except Exception as e:
        return f"[searchWeb 错误] {e}"

    if resp.status_code != 200:
        return f"[searchWeb 错误] HTTP {resp.status_code}: {resp.text[:300]}"

    try:
        data = resp.json()
    except Exception:
        return f"[searchWeb 错误] 响应 JSON 解析失败: {resp.text[:300]}"

    # 百度返回的 references 数组
    refs = data.get("references", [])
    if not refs:
        # 可能有错误码
        err_code = data.get("code")
        err_msg = data.get("message", "")
        if err_code:
            return f"[searchWeb API 错误] code={err_code}, message={err_msg}"
        return f"[searchWeb] 未找到与 \"{query}\" 相关的结果"

    # 格式化输出
    lines = [f"搜索 \"{query}\" 共找到 {len(refs)} 条结果:"]
    for i, r in enumerate(refs, 1):
        title = r.get("title", "(无标题)")
        url = r.get("url", "(无链接)")
        snippet = r.get("snippet", "") or r.get("content", "") or ""
        # 截断 snippet 避免过长
        if len(snippet) > 200:
            snippet = snippet[:200] + "..."
        lines.append(f"\n{i}. {title}\n   URL: {url}\n   摘要: {snippet}")

    return "\n".join(lines)


# ============================================================
# fetchWeb —— subprocess + curl + trafilatura 抓网页正文
# ============================================================

def fetchWeb(url: str, max_chars: int = 4000) -> str:
    """抓取指定 URL 的网页正文,转换为 Markdown 后返回。

    Args:
        url: 目标网页 URL。
        max_chars: 返回正文的最大字符数,默认 4000。

    Returns:
        Markdown 格式的网页正文;失败时返回错误信息。
    """
    if not url or not url.strip():
        return "[fetchWeb 参数错误] url 不能为空"

    # 先确认 curl 可用
    curl_exe = _find_curl()
    if curl_exe is None:
        return "[fetchWeb 不可用] 系统中未找到 curl,请确保 curl 在 PATH 中"

    # 第一步: subprocess 调 curl 拿 HTML
    try:
        html_bytes = _curl_fetch(curl_exe, url)
    except subprocess.TimeoutExpired:
        return f"[fetchWeb 错误] 抓取超时 (30s): {url}"
    except Exception as e:
        return f"[fetchWeb 错误] curl 执行失败: {e}"

    if not html_bytes:
        return f"[fetchWeb 错误] 抓取到空内容: {url}"

    # 第二步: trafilatura 提正文 + 转 Markdown
    if trafilatura is None:
        # 降级: 直接返回原始 HTML 的前 N 字符
        return (
            f"[fetchWeb 提示] trafilatura 未安装,返回原始 HTML 片段:\n"
            f"pip install trafilatura 以获得更好的正文提取\n\n"
            f"--- 原始 HTML (前 {max_chars} 字符) ---\n"
            f"{html_bytes.decode('utf-8', errors='ignore')[:max_chars]}"
        )

    try:
        html_text = html_bytes.decode("utf-8", errors="ignore")
    except Exception as e:
        return f"[fetchWeb 错误] HTML 解码失败: {e}"

    try:
        # trafilatura.extract 支持 output_format='markdown'
        markdown = trafilatura.extract(
            html_text,
            output_format="markdown",
            include_links=True,
            include_images=False,
            favor_precision=True,
        )
    except Exception as e:
        return f"[fetchWeb 错误] trafilatura 提取失败: {e}"

    if not markdown:
        return (
            f"[fetchWeb 警告] 未能从该页面提取有效正文 (可能是登录页/JS 渲染页/纯图片页)\n"
            f"尝试原始 HTML 片段:\n"
            f"{html_text[:max_chars]}"
        )

    # 截断保护
    if len(markdown) > max_chars:
        markdown = markdown[:max_chars] + "\n\n...(内容已截断)"

    return f"# 网页内容: {url}\n\n{markdown}"


def _find_curl() -> str | None:
    """找 curl.exe。Windows 上通常在 C:\\Windows\\System32\\curl.exe。"""
    candidates = [
        r"C:\Windows\System32\curl.exe",
        "curl",  # 或者在 PATH 里
    ]
    for c in candidates:
        try:
            if Path(c).exists():
                return c
        except Exception:
            pass
        # 用 where 检查 PATH
        try:
            result = subprocess.run(
                ["where.exe", "curl"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                return result.stdout.strip().splitlines()[0]
        except Exception:
            pass
    return None


def _curl_fetch(curl_exe: str, url: str) -> bytes:
    """用 curl 以参数列表方式 (不用 shell) 抓取网页 HTML。

    选用 -L 跟随重定向,--connect-timeout 10,--max-time 30。
    加 User-Agent 避免被部分站点拒绝。
    """
    args = [
        curl_exe,
        "-sS",          # 静默但保留错误
        "-L",           # 跟随 301/302
        "--connect-timeout", "10",
        "--max-time", "30",
        "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) xAgent/1.0",
        "-H", "Accept: text/html,application/xhtml+xml",
        url,
    ]
    result = subprocess.run(
        args,
        capture_output=True,
        timeout=45,
        shell=False,  # 重要: 不用 shell=True,符合安全要求
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"curl 返回码 {result.returncode}: "
            f"{result.stderr.decode('utf-8', errors='ignore')[:300]}"
        )
    return result.stdout

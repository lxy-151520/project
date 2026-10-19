"""
Practice02 - 任务(二)：新增 isLeapYear 工具
在 chat-stream-tool-getDate.py 基础上，再加一个计算闰年的 function call
用 Python 代码判断闰年（不是让 AI 回答）
"""
import configparser
import json
import time
import os
import subprocess
import requests

# ---------- 1. 读取配置 ----------
config = configparser.ConfigParser()
config.read('config.ini', encoding='utf-8')
api_key = config['llm']['api_key']
base_url = config['llm']['base_url']
model = config['llm']['model']

# ---------- 2. 定义工具列表（两个 tool）----------
tools = [
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑的日期和时间",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": "判断某一年是否是闰年",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "要判断的年份，例如 2024",
                    }
                },
                "required": ["year"],
            },
        },
    },
]

# ---------- 3. 工具实现 ----------
def getDate():
    """调用 Windows 本地 date 和 time 命令获取日期时间"""
    try:
        date_out = subprocess.run(['cmd', '/c', 'date /t'], capture_output=True, text=True).stdout.strip()
        time_out = subprocess.run(['cmd', '/c', 'time /t'], capture_output=True, text=True).stdout.strip()
        return f"当前日期: {date_out}, 当前时间: {time_out}"
    except Exception:
        d = os.popen('date /t').read().strip()
        t = os.popen('time /t').read().strip()
        return f"当前日期: {d}, 当前时间: {t}"


def isLeapYear(year):
    """Python 代码判断闰年"""
    year = int(year)
    if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
        return f"{year} 年是闰年（2 月有 29 天，全年 366 天）"
    else:
        return f"{year} 年不是闰年（2 月有 28 天，全年 365 天）"


tool_map = {
    "getDate": getDate,
    "isLeapYear": isLeapYear,
}

# ---------- 4. 发送请求 ----------
def call_llm(messages):
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "tools": tools,
        },
    )
    return resp.json()

# ---------- 5. 流式输出 ----------
def stream_response(messages):
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "stream": True,
        },
        stream=True,
    )
    full_text = ""
    for line in resp.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if not line.startswith("data: "):
            continue
        data = line[6:]
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        delta = chunk["choices"][0]["delta"].get("content", "")
        for ch in delta:
            print(ch, end="", flush=True)
            time.sleep(0.02)
            full_text += ch
    print()
    return full_text

# ---------- 6. 主循环 ----------
messages = [
    {"role": "system", "content": "你是一个实用的 AI 助手，需要时调用工具获取信息。"}
]

print("开始对话（Ctrl+C 退出）")
print("试试问：'今天日期'、'2024年是闰年吗'、'2000年和1900年哪个是闰年'")
print("-" * 40)

while True:
    user_input = input("\n你: ")
    if not user_input.strip():
        continue

    messages.append({"role": "user", "content": user_input})

    resp = call_llm(messages)
    message = resp["choices"][0]["message"]

    while resp["choices"][0]["finish_reason"] == "tool_calls":
        tool_calls = message.get("tool_calls", [])
        messages.append(message)

        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            tool_call_id = tc["id"]
            arguments = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}

            func = tool_map.get(tool_name)
            if func:
                result = func(**arguments) if arguments else func()
            else:
                result = f"未知工具: {tool_name}"

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": result,
            })

        resp = call_llm(messages)
        message = resp["choices"][0]["message"]

    print("AI: ", end="", flush=True)
    final_text = stream_response(messages)
    messages.append({"role": "assistant", "content": final_text})

"""
Practice02 - 任务(一)：function call 获取日期
基于 chat_v3_loop.py，新增 getDate function call tool
使用本地 date 命令获取当前日期和时间
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

# ---------- 2. 定义工具列表（function call 描述）----------
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
    }
]

# ---------- 3. 工具实现（调用本地 date 命令）----------
def getDate():
    """调用 Windows 本地 date 和 time 命令获取日期时间"""
    try:
        date_out = subprocess.run(['cmd', '/c', 'date /t'], capture_output=True, text=True).stdout.strip()
        time_out = subprocess.run(['cmd', '/c', 'time /t'], capture_output=True, text=True).stdout.strip()
        return f"当前日期: {date_out}, 当前时间: {time_out}"
    except Exception as e:
        # 备选：用 os.popen
        d = os.popen('date /t').read().strip()
        t = os.popen('time /t').read().strip()
        return f"当前日期: {d}, 当前时间: {t}"

# 工具名 → 函数映射
tool_map = {
    "getDate": getDate,
}

# ---------- 4. 发送请求（带 tools）----------
def call_llm(messages):
    """发送请求到 LLM，返回完整的 response 对象（非流式，以便处理 tool_calls）"""
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

# ---------- 5. 流式输出工具函数（当无 tool_calls 时）----------
def stream_response(messages):
    """流式输出 LLM 回复文本"""
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

# ---------- 6. 主循环（无限对话 + function call 处理）----------
messages = [
    {"role": "system", "content": "你是一个实用的 AI 助手，需要时调用工具获取信息。"}
]

print("开始对话（Ctrl+C 退出），试试问：'今天日期是多少？'")
print("-" * 40)

while True:
    user_input = input("\n你: ")
    if not user_input.strip():
        continue

    messages.append({"role": "user", "content": user_input})

    # 先问一次 LLM（非流式，判断是否要调用工具）
    resp = call_llm(messages)
    message = resp["choices"][0]["message"]

    # 如果 LLM 要调用工具
    while resp["choices"][0]["finish_reason"] == "tool_calls":
        tool_calls = message.get("tool_calls", [])
        messages.append(message)  # 把 assistant 的 tool_calls 消息加进去

        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            tool_call_id = tc["id"]

            # 执行工具
            func = tool_map.get(tool_name)
            if func:
                result = func()
            else:
                result = f"未知工具: {tool_name}"

            # 把工具结果加进 messages
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": result,
            })

        # 再次请求 LLM（看是否还要调工具，或给最终回答）
        resp = call_llm(messages)
        message = resp["choices"][0]["message"]

    # LLM 给最终文本回复 —— 用流式输出
    print("AI: ", end="", flush=True)
    final_text = stream_response(messages)
    messages.append({"role": "assistant", "content": final_text})

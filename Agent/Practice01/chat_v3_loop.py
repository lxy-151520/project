"""
Practice01 - 第3步：无限循环对话
不断问答，直到 Ctrl+C 强行退出
"""
import configparser
import json
import time
import requests

# 读取配置
config = configparser.ConfigParser()
config.read('config.ini', encoding='utf-8')
api_key = config['llm']['api_key']
base_url = config['llm']['base_url']
model = config['llm']['model']

print("开始对话（Ctrl+C 退出）")
print("-" * 40)

# 无限循环
while True:
    # 用户输入
    user_input = input("\n你: ")

    # 调用 LLM（流式）
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": user_input}],
            "stream": True,
        },
        stream=True,
    )

    # 逐字打印
    print("AI: ", end="", flush=True)
    for line in response.iter_lines():
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
            time.sleep(0.03)
    print()

"""
Practice01 - 第4步：带聊天记忆
每次循环把之前所有聊天记录发送给 LLM，实现连续对话
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

# 聊天记录（带记忆）
messages = []

print("开始对话（Ctrl+C 退出）")
print("-" * 40)

# 无限循环
while True:
    # 用户输入
    user_input = input("\n你: ")

    # 把用户消息加入记录
    messages.append({"role": "user", "content": user_input})

    # 调用 LLM（流式），把全部历史记录发给模型
    response = requests.post(
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

    # 逐字打印，同时收集完整回复
    print("AI: ", end="", flush=True)
    full_reply = ""
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
        full_reply += delta

    # 把 AI 回复加入记录，下一轮会带上
    messages.append({"role": "assistant", "content": full_reply})
    print()

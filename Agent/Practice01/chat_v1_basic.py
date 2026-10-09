"""
Practice01 - 第1步：非流式一次性对话
用 config.ini 配置 LLM，发送一条消息，等全部生成完再打印
"""
import configparser
import requests

# 读取配置
config = configparser.ConfigParser()
config.read('config.ini', encoding='utf-8')
api_key = config['llm']['api_key']
base_url = config['llm']['base_url']
model = config['llm']['model']

# 用户输入
user_input = input("你: ")

# 调用 LLM（非流式）
response = requests.post(
    f"{base_url}/chat/completions",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={
        "model": model,
        "messages": [{"role": "user", "content": user_input}],
    },
)

# 打印回复
reply = response.json()["choices"][0]["message"]["content"]
print(f"AI: {reply}")

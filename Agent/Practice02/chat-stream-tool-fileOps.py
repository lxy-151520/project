"""
Practice02 - 任务(三)：10 个本地文件操作 function call
基于 chat-stream-tool-isLeapYear.py，新增 10 个文件系统工具
"""
import configparser
import json
import time
import os
import shutil
import requests

# ---------- 1. 读取配置 ----------
config = configparser.ConfigParser()
config.read('config.ini', encoding='utf-8')
api_key = config['llm']['api_key']
base_url = config['llm']['base_url']
model = config['llm']['model']

# ---------- 2. 工具定义 ----------
tools = [
    # 之前的工具
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑的日期和时间",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": "判断某一年是否是闰年",
            "parameters": {
                "type": "object",
                "properties": {"year": {"type": "integer", "description": "要判断的年份"}},
                "required": ["year"],
            },
        },
    },
    # 10 个文件操作工具
    {
        "type": "function",
        "function": {
            "name": "getCWD",
            "description": "获取当前工作目录（程序运行时所在的目录）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listDir",
            "description": "列出指定目录下所有文件和子目录的名称",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径，不传则用当前目录"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getFileType",
            "description": "获取指定文件的类型（扩展名），如 .txt .py .mp4",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件的完整路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "readFile",
            "description": "读取指定文本文件的全部内容（仅支持纯文本格式）",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "要读取的文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createFile",
            "description": "在指定目录创建一个新的纯文本文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir": {"type": "string", "description": "目标目录，不传则用当前目录"},
                    "filename": {"type": "string", "description": "文件名，例如 test.txt"},
                    "content": {"type": "string", "description": "初始内容，不传则创建空文件"},
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "editFile",
            "description": "编辑指定纯文本文件的内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要编辑的文件路径"},
                    "content": {"type": "string", "description": "要写入的文本内容"},
                    "mode": {"type": "string", "enum": ["overwrite", "append"], "description": "overwrite=覆盖(默认), append=追加到末尾"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createDir",
            "description": "创建一个新的目录（文件夹），会自动创建中间层级",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "要创建的目录路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteDir",
            "description": "删除指定目录，无论是否为空都会被彻底删除",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "要删除的目录路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteFile",
            "description": "删除指定的文件",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "要删除的文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename",
            "description": "重命名文件或目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "old_path": {"type": "string", "description": "原始路径"},
                    "new_path": {"type": "string", "description": "新路径或新名字"},
                },
                "required": ["old_path", "new_path"],
            },
        },
    },
]

# ---------- 3. 工具实现 ----------
def getDate():
    import subprocess
    try:
        d = subprocess.run(['cmd', '/c', 'date /t'], capture_output=True, text=True).stdout.strip()
        t = subprocess.run(['cmd', '/c', 'time /t'], capture_output=True, text=True).stdout.strip()
        return f"当前日期: {d}, 当前时间: {t}"
    except Exception:
        d = os.popen('date /t').read().strip()
        t = os.popen('time /t').read().strip()
        return f"当前日期: {d}, 当前时间: {t}"


def isLeapYear(year):
    year = int(year)
    if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
        return f"{year} 年是闰年（2 月有 29 天，全年 366 天）"
    return f"{year} 年不是闰年（2 月有 28 天，全年 365 天）"


def getCWD():
    return os.getcwd()


def listDir(path=None):
    target = path if path else os.getcwd()
    try:
        items = os.listdir(target)
        result = []
        for item in items:
            full = os.path.join(target, item)
            if os.path.isdir(full):
                result.append(f"[文件夹] {item}")
            elif os.path.isfile(full):
                size = os.path.getsize(full)
                result.append(f"[文件]   {item} ({size} 字节)")
            else:
                result.append(f"[其他]   {item}")
        if not result:
            return f"目录 {target} 是空的"
        return f"目录 {target} 下有 {len(result)} 项:\n" + "\n".join(result)
    except Exception as e:
        return f"列出目录失败: {str(e)}"


def getFileType(path):
    try:
        if not os.path.exists(path):
            return f"文件不存在: {path}"
        ext = os.path.splitext(path)[1]
        if ext:
            return f"{os.path.basename(path)} 的类型是 {ext}"
        return f"{os.path.basename(path)} 没有扩展名"
    except Exception as e:
        return f"获取文件类型失败: {str(e)}"


def readFile(path):
    try:
        if not os.path.exists(path):
            return f"文件不存在: {path}"
        if os.path.isdir(path):
            return f"这是文件夹，不能读取: {path}"
        ext = os.path.splitext(path)[1].lower()
        binary_exts = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.mp3', '.mp4',
                       '.avi', '.mov', '.pdf', '.zip', '.rar', '.exe', '.dll', '.pyc'}
        if ext in binary_exts:
            return f"文件 {path} 是二进制格式（{ext}），不支持读取"
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        if len(content) > 3000:
            content = content[:3000] + "\n... (内容过长，只显示前3000字符)"
        return content
    except Exception as e:
        return f"读取文件失败: {str(e)}"


def createFile(filename, dir=None, content=""):
    try:
        d = dir if dir else os.getcwd()
        if not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
        filepath = os.path.join(d, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        size = os.path.getsize(filepath)
        return f"文件创建成功: {filepath} ({size} 字节)"
    except Exception as e:
        return f"创建文件失败: {str(e)}"


def editFile(path, content, mode="overwrite"):
    try:
        if not os.path.exists(path):
            return f"文件不存在: {path}"
        if mode == "append":
            with open(path, 'a', encoding='utf-8') as f:
                f.write(content)
            return f"已追加内容到 {path}"
        else:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"已覆盖写入 {path}"
    except Exception as e:
        return f"编辑文件失败: {str(e)}"


def createDir(path):
    try:
        if os.path.exists(path):
            return f"目录已存在: {path}"
        os.makedirs(path, exist_ok=True)
        return f"目录创建成功: {path}"
    except Exception as e:
        return f"创建目录失败: {str(e)}"


def deleteDir(path):
    try:
        if not os.path.exists(path):
            return f"目录不存在: {path}"
        if os.path.isfile(path):
            return f"这是文件，不是目录: {path}"
        shutil.rmtree(path)
        return f"目录已删除（含所有内容）: {path}"
    except Exception as e:
        return f"删除目录失败: {str(e)}"


def deleteFile(path):
    try:
        if not os.path.exists(path):
            return f"文件不存在: {path}"
        if os.path.isdir(path):
            return f"这是目录，不是文件: {path}"
        os.remove(path)
        return f"文件已删除: {path}"
    except Exception as e:
        return f"删除文件失败: {str(e)}"


def rename(old_path, new_path):
    try:
        if not os.path.exists(old_path):
            return f"源路径不存在: {old_path}"
        os.rename(old_path, new_path)
        return f"重命名成功: {old_path} -> {new_path}"
    except Exception as e:
        return f"重命名失败: {str(e)}"


tool_map = {
    "getDate": getDate, "isLeapYear": isLeapYear,
    "getCWD": getCWD, "listDir": listDir,
    "getFileType": getFileType, "readFile": readFile,
    "createFile": createFile, "editFile": editFile,
    "createDir": createDir, "deleteDir": deleteDir,
    "deleteFile": deleteFile, "rename": rename,
}

# ---------- 4. LLM 请求 ----------
def call_llm(messages):
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "tools": tools},
    )
    return resp.json()


def stream_response(messages):
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "stream": True},
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

# ---------- 5. 主循环 ----------
if __name__ == "__main__":
    messages = [
        {"role": "system", "content": "你是一个实用的 AI 助手，擅长使用工具操作本地文件系统。"}
    ]

    print("=" * 50)
    print("Practice02 任务(三)：文件操作工具对话")
    print("可提问：当前目录、列出文件、读取/创建/编辑/删除/重命名")
    print("Ctrl+C 退出")
    print("=" * 50)

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
                arguments = json.loads(tc["function"]["arguments"] or "{}")
                func = tool_map.get(tool_name)
                if func:
                    print(f"\n  [调用工具] {tool_name}({arguments})")
                    result = func(**arguments) if arguments else func()
                    print(f"  [工具返回] {result[:200]}{'...' if len(result) > 200 else ''}")
                else:
                    result = f"未知工具: {tool_name}"
                messages.append({"role": "tool", "tool_call_id": tool_call_id,
                                 "name": tool_name, "content": result})
            resp = call_llm(messages)
            message = resp["choices"][0]["message"]

        print("\nAI: ", end="", flush=True)
        final_text = stream_response(messages)
        messages.append({"role": "assistant", "content": final_text})

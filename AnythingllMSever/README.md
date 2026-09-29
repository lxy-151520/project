# AnythingLLM 文档上传页面

单文件网页，调用 AnythingLLM Developer API 的 `POST /v1/document/upload` 接口上传文档，并自动向量化嵌入到**第一个工作区**。

## 使用

1. 启动静态服务（页面不能用 file:// 直接打开，需要跨域支持）：

   ```bash
   python -m http.server 8000
   ```

   工作目录：本项目目录。

2. 浏览器打开：**http://localhost:8000/index.html**

3. 选择文件 → 点击「上传」→ 页面显示接口返回的 JSON。

## 实现流程

1. `GET http://localhost:3001/api/v1/workspaces`
   带 `Authorization: Bearer <开发者API key>`，取 `workspaces[0].slug`（即第一个工作区「我的工作区」）。
2. `POST http://localhost:3001/api/v1/document/upload`
   `multipart/form-data`，字段：
   - `file`：文件本体
   - `addToWorkspaces`：上一步取到的 slug，服务端上传后自动解析并向量化嵌入该工作区

## 配置

API key 在 `index.html` 顶部：

```js
const API = "http://localhost:3001/api";
const KEY = "<你的开发者API key>";
```

注意：`KEY` 必须是 AnythingLLM **Settings → Developer API** 生成的开发者 key，**不是** `.env` 里模型提供商（如 SiliconFlow）的 `sk-` key，用错会返回 403。

## 接口文档

- Swagger UI：http://localhost:3001/api/docs/#/Douuments/post_v1_document_upload

## 文件

- `index.html` — 页面本体（HTML + CSS + JS 全在一个文件内，无依赖、无构建）
- `README.md` — 本说明

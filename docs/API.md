# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

## 接收身份与同内容重发

每次物理送达（`POST /api/runs` 或 `/api/upload`）都生成唯一 `receipt_id`，响应附带 `receipt_id` 与 `delivery_status`（`created` 首次建批 / `merged` 同内容归并）。批次身份 `run_id` 由规范化内容指纹（忽略编码差异与列顺序）、参数和规则版本决定：换编码或换列顺序的同内容重发归为同一批次，不新增批次、不重复计数，每次送达的原文件各自留存；访问值真变化则另立新批次。

- `GET /api/receipts`：全部接收记录（含失败送达），可加 `?run_id=<id>` 只看某批次。
- `GET /api/receipts/<receipt_id>`：单条接收记录元数据（状态、编码、列序、输入摘要、内容指纹、失败原因）。
- `GET /api/receipts/<receipt_id>/raw`：追回当次送达的原始文件字节。

判定失败（编码、表头、空态等）返回原有错误码，不创建批次、不改动既有批次版本，失败原文件以 `status=failed` 留存且可通过上述接口追回。`GET /api/runs` 历史中每个批次带 `deliveries` 送达次数。

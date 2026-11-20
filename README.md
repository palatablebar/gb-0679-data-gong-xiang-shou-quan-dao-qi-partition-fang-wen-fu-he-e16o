# 数据共享授权到期与分区访问复核

供企业数据共享审计专员核对原始记录、处理差异并封存证据。

## 启动

```sh
docker compose up --build -d
docker compose exec -T app pytest -q
```

打开 http://localhost:18248 。首次进入自动运行仓内脏样例。工具条可重跑、切换样例或上传CSV。SQLite保存在命名卷records中，重建服务保留批次。

## 模块

- 1. 访问采信：`/accesses`，`/api/accesses`。
- 2. 资源映射：`/resources`，`/api/resources`。
- 3. 授权定版：`/grants`，`/api/grants`。
- 4. 冲突裁决：`/conflicts`，`/api/conflicts`。
- 5. 分区判定：`/partitions`，`/api/partitions`。
- 6. 访问对账：`/audit`，`/api/audit`。
- 7. 审计归档：`/seals`，`/api/seals`。

## 核心规则

拒绝规则优先于允许，授权必须同时命中资源、分区和生效窗；显式拒绝不得被宽授权覆盖。

## 演示

1. 打开首页，核对当次计算、差异和隔离原因。
2. 切换模块查看源行及裁决依据。
3. 重跑相同样例，批次号与行数保持一致；换编码（legacy.csv）或换列顺序的同内容重发归为同一批次，页面显示“同内容归并”，送达次数增加但计数不变，每份原文件可在接收记录中追回。
4. 复核后导出一份证据CSV（含每次送达的receipt证据行）。版本已变化的复核提交返回409。

## 接收身份与重发归并

每次物理送达生成唯一接收身份 `receipt_id`；批次身份由与编码、列顺序无关的规范化内容指纹决定。同内容重试只新增接收记录、不新增批次或计数，原文件逐份留存（`GET /api/receipts/<id>/raw` 追回）；访问值真变化才另立批次。判定失败时恢复并保留旧版，失败原文件仍以 failed 接收记录留存。

`POST /api/runs` 接收sample或csv；`GET /api/runs`返回历史批次（含deliveries送达次数）；`POST /api/runs/<id>/review`需要version与decision；`GET /api/runs/<id>/archive`返回唯一证据导出。`GET /api/receipts`返回全部接收记录（含失败送达）。

## 输入与输出

输入列见 `docs/DATA-DICTIONARY.md`。项目包含dirty.csv、clean.csv、legacy.csv，统一走实际导入路径。上传限制4MB，拒绝不带时区的时间。业务键按字符串保留，Decimal参与计算，空值不会当零。

## 范围

样例均为虚构。单机复核工具不连接生产系统；不提供登录、远端数据库或自动支付。内存计算按4MB输入上限控制，SQLite事务保证结果完整写入。

## 目录

app为服务与规则，sample_data为输入，tests为测试，docs为定义与深度登记。

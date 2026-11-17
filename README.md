# 非遗市集摊位与活动日程的变更采集

这是非遗市集资料的本地演练门户与目录采集器。演练数据仅在环回地址提供，不会操作真实用户、订单或商户。

## 采集链路

- `app.capture.read_catalog` 读取目录月份卡片；
- `app.capture.read_detail_entry` 走卡片到详情并接收可选业务选择；
- `app.capture.read_calendar` 沿日历导航巡查：月份选择 → 单日抽屉（`#day`）→ 摊位弹窗（`#stall-detail`），逐层读取并校验内容自带的月份/日期前缀与当前导航一致；
- `app.domain` 把页面信号解释为业务事实，业务键为 `活动:月份:日期`，同名活动在不同日期重演天然区分；
- `app.records.save_calendar_observations` 将每次观察追加到 `calendar_visits`，并通过状态机维护当前事实表 `calendar_facts`；
- `app.review.review_calendar` 汇总月份视图与追溯链。

## 防覆盖与缺口规则

- 抽屉/弹窗的“读取中”与空白是过渡态，不会被当成撤场；
- 跨月缓存内容（前缀与当前月份/日期不符）记为 `stale-cache` 缺口，不落为旧安排；
- 已撤场（`cancelled`）的业务键拒绝后续在档观察“复活”，重跑不会把取消覆盖回旧安排；
- 摊位归属等内容变化生成事实新版本（`revise`），历史观察仍只追加保留在访问表；
- 幂等重跑（内容未变）记为 `keep`，不新增版本；
- 一个月份只有全部活动 × 全部日期都有权威事实才是 `published`，否则是带 `missing` 缺口的 `draft`。

站点约定见 `docs/portal.md`；测试时从本地任意空闲端口启动演练站点。安装锁定依赖并准备 Chromium 后：

- `python -m unittest discover -s tests -v`：运行全部测试（含真实 Chromium 巡查）。
- `python -m compileall -q app tests`：检查代码。
- `python -m app.site`：启动本地演练站点。
- `python -m app.cli`：另一个终端观察目录输出；`python -m app.cli calendar heritage-11` 观察日历巡查输出。

两个终端命令用于人工演示，自动测试不依赖固定端口。

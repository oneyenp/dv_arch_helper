# 模块交互关系分析与展示实施计划

## 1. 总结

以指定目标模块为中心，从 `simv.daidir` 批量提取端口和静态连接，穿透 net、层级端口、alias 及无逻辑运算的连续赋值，形成稳定的模块交互 JSON 模型。

一期提供 JSON、CSV、XLSX 表格报告；二期基于同一模型提供单用户本地 WebUI。接口分组支持自动、手动和关闭三种模式，时钟域默认启用。

## 2. 一期：抽取、建模与表格

- 先实现 NPI 探测工具，确认当前 Verdi 版本的实例、端口、net、assign、时钟及 SDC Python API；生产代码通过 adapter 隔离版本差异，不假定 Tcl API 可直接映射。
- 每次运行只加载一次设计数据库，批量建立实例、端口、net 和连接索引，再处理目标模块全部端口。
- 按方向追踪：
  - `input` 向上游驱动追踪。
  - `output` 向下游负载追踪。
  - `inout` 双向追踪。
- 可穿透简单引用、bit/part select、纯引用拼接、层级穿接和 alias；遇到运算表达式、常量、primitive、过程块、寄存器或未知对象时停止并记录原因。
- 每个目标端口必须输出结果，对端分类固定为 `sibling_port`、`parent_boundary`、`unconnected` 或 `trace_stopped`；多驱动、多负载拆成多条关系。
- 自动分组按 RTL 声明顺序扫描相邻端口，以最长公共字符前缀形成最大连续组；默认最小前缀长度为 3、至少 2 个信号。其余信号进入 `ungrouped`。
- 手动分组读取 JSON：相同 `group_name` 即同组；重复归属、空组名或不存在的端口视为配置错误。`off` 模式完全跳过聚合。
- 时钟域默认开启，NPI 为主要来源，可选 SDC 补充缺失信息；冲突保留 NPI 结论、降低置信度并生成诊断，不按端口名称猜测。支持 `--no-clock-domain`。
- XLSX 包含 `Summary`、`Interfaces`、`Relations`、`Diagnostics`；关系明细按接口组折叠，支持筛选和展开。CSV 每条端口关系一行，通过 `group_id` 聚合。

## 3. 公共接口与数据契约

新增统一入口：

```bash
python3 scripts/extract_module_interactions.py \
  --dbdir simv.daidir \
  --scope tb_top.u_dut \
  --rtl rtl/dut.sv \
  --sdc constraints/top.sdc \
  --group-mode auto \
  --format xlsx \
  --output interactions.xlsx
```

可选参数包括：

```text
--group-mode auto|manual|off
--group-config <groups.json>
--min-prefix-length 3
--no-clock-domain
--format json|csv|xlsx
```

规范 JSON 使用版本化 `InteractionModel`，包含：

- `metadata`：schema 版本、scope、输入摘要、生成时间和功能开关。
- `modules`、`ports`：完整层级名、方向、位宽、声明顺序及源码信息。
- `relations`：目标端口、对端端口、方向、追踪路径摘要和终止分类。
- `interface_groups`：组名、成员、来源 `auto_lcp|manual` 及公共前缀。
- `clock_domains`：两端时钟数组、关系、来源和置信度。
- `diagnostics`：阶段、对象、严重级别、错误码和说明。

ID 由 scope、完整端口名和关系端点确定性生成，保证重复运行和二期 WebUI 引用稳定。

手动配置采用版本化 JSON：

```json
{
  "schema_version": "1.0",
  "scope": "tb_top.u_dut",
  "groups": [
    {
      "group_name": "request_channel",
      "ports": [
        "tb_top.u_dut.req_valid",
        "tb_top.u_dut.req_data"
      ]
    }
  ]
}
```

## 4. 二期：本地 WebUI

- 使用 Python FastAPI 加载一期 JSON，React/Vite 前端使用虚拟滚动表格，部署在安装了 Verdi/NPI 的 Linux 主机，通过浏览器端口访问。
- 主视图按接口组展示目标模块与并行模块关系，可按需展开到对端端口；支持模块、方向、时钟域、CDC 和诊断状态过滤。
- 关系图仅渲染当前筛选或选中的接口组，采用“目标模块居中、并行模块分列”的布局，避免一次绘制数千信号。
- 支持多选端口并填写组名，保存为一期相同的手动分组 JSON；不引入账号、中心数据库或多人协作。
- API 提供分页关系查询、接口组查询、诊断查询、分组配置读写和报告重新加载。

## 5. 错误处理

- `VERDI_HOME`/NPI 导入失败、数据库打不开、目标 scope 不存在、手动配置非法属于致命错误：返回非零退出码，不生成看似成功的报告。
- 单端口方向、位宽、追踪或时钟域解析失败属于局部诊断：保留该端口和已知字段，未知值显式写为 `unknown`。
- alias/assign 环路通过 visited set 截断，并写入 `Diagnostics`。
- 输出先写同目录临时文件，完整序列化成功后原子替换目标文件，避免中断留下半份报告。

## 6. 测试与验收

- 单元测试覆盖三种分组模式、最长公共前缀边界、稳定 ID、手动配置校验、多扇出、环路截断、未知值传播和三种输出的一致性。
- adapter 集成测试覆盖同网连接、跨层级端口、alias、连续赋值、part select、纯引用拼接、父级边界、未连接及逻辑终止。
- 在真实 Verdi 环境中对照人工追踪结果验证 sibling port、assign、多负载、CDC 和 SDC 补充行为。
- 性能夹具包含 10,000 个目标端口、50 个同级模块和最多 30,000 条关系；不含数据库加载时间，建模、分组及三种报告生成合计不超过 30 秒，峰值内存不超过 1GB。
- 致命初始化、scope 或配置错误返回非零退出码且不留下半份报告；单端口失败保留已知结果并写入 `Diagnostics`。
- 一期验收以 JSON/CSV/XLSX 内容一致、接口组可展开到端口关系、默认显示时钟域且全部目标端口均有分类结果为准。

## 7. 实施顺序

1. 探测并记录目标 Verdi 环境实际可用的 Python NPI API。
2. 定义版本化 `InteractionModel`、稳定 ID 和诊断结构。
3. 实现 NPI adapter、批量索引和有界静态连接追踪。
4. 实现自动、手动和关闭三种接口分组模式。
5. 接入 NPI 时钟域与可选 SDC 补充逻辑。
6. 实现 JSON、CSV、XLSX 输出及原子写入。
7. 完成单元、集成、性能和真实 NPI smoke test。
8. 一期验收稳定后，基于同一 JSON 契约实施本地 WebUI。

## 8. 已确认的默认值与边界

- 一期展示载体为 CSV/XLSX 和配置文件，不实现交互式 UI。
- 关系事实粒度为端口到端口，主视图按接口组到模块聚合，并可展开查看对端端口。
- 静态连接追踪不穿透组合或时序逻辑锥。
- 父级边界、未连接和追踪终止端口全部保留并分类。
- 自动分组采用连续信号名称的最长公共字符前缀，默认最小长度为 3。
- 手动分组以用户填写的相同组名为唯一归组依据，不使用通配符或正则表达式。
- 时钟域显示默认开启，来源为 NPI 加可选 SDC。
- 二期采用本地或远程 Linux 主机上的单用户 WebUI，不建设中心化多人服务。

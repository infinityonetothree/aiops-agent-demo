# 面试演示手册（当前可运行版本）

## 先说明项目边界

这份代码是根据《项目介绍.md》重新实现的当前版本，已经跑通 **Docker 工作负载 + Prometheus + 本地 Qwen3 Agent 诊断 + 规则基线 + 授权重启 + 隔离代码修复与门禁**。本地 Agent 使用 RTX 3070、受限工具调用和结构化输出，不需要云端 API key。Claude 仅保留为可选适配器；GitHub PR、Milvus、Jaeger 与 Kubernetes 还没有实现。

## 现场演示：约 3–5 分钟

确保 Docker Desktop 显示 **Engine running**。在 Windows PowerShell 中：

```powershell
cd C:\Users\31570\Desktop\codex_Agent\aiops-agent
py -m unittest discover -s tests -v
.\scripts\demo_agent.ps1
.\scripts\demo.ps1
.\scripts\demo_repair.ps1
```

若 PowerShell 限制脚本执行，可只对当前进程放开：

```powershell
Set-ExecutionPolicy -Scope Process RemoteSigned
.\scripts\demo.ps1
```

脚本依次构建并启动本地容器、等待指标增长、保存只读诊断、执行一次授权重启、保存重启后的指标，最后停止容器。证据写入 `reports/demo-时间戳/`；报告中的重点字段是 `diagnosis.evidence`、`route`、`executed_actions[0].command_succeeded` 和 `health_verified`。

`./scripts/demo_agent.ps1` 会额外启动本地 Ollama，并让 Qwen3 4B 主动调用只读观测工具后输出诊断。模型已保存在 Docker volume；正常复演不再下载 2.5 GB 文件。重点展示 `agent_run.provider=ollama`、`tool_called=true`、推理耗时和 `total_cost_usd=0.0`。

想让容器留在运行状态供现场查看，可执行 `./scripts/demo.ps1 -KeepRunning`；演示结束后用 `docker compose stop` 停止泄漏服务。

## 讲解顺序

1. **真实工作负载**：打开 `fixtures/recommendation/recommendation_server.py`，指出 `_seen_product_ids.extend(product_ids)` 会无界增长；容器内存限制为 128 MiB。
2. **可观测证据**：打开 `before.metrics.txt` 与 `readonly.json`，指出 Prometheus 样本增长及 Docker 运行状态。可在 `http://127.0.0.1:9090` 查询 `recommendation_seen_products`；脚本默认会停止容器，如需看实时页面请用 `-KeepRunning`。
3. **受控决策**：只读诊断输出 `human_review_online_op_code_fix_pending`，`executed_actions` 为空。解释模型或规则给出建议后，由代码决定是否允许执行。
4. **临时止血**：展示 `restart.json` 的 `auto_remediated_code_fix_pending`，以及重启命令成功、健康检查通过。对比 `before.metrics.txt` 和 `after.metrics.txt`，说明重启清空了进程内累积状态。
5. **安全边界**：打开 `aiops/remediate.py`，指出目标名、Compose 项目标签、服务标签三重核验；命令由固定参数数组构造，不接受模型生成的 shell 字符串。未经 `--apply-low-risk` 不会重启。
6. **转入根因修复**：重启只能缓解，原始泄漏代码仍在；继续运行修复演示，展示隔离补丁和测试门禁。GitHub PR 仍是下一阶段。

## 代码修复演示：约 1 分钟

运行 `./scripts/demo_repair.ps1` 后，打开最新的 `reports/repair-时间戳/repair.patch` 和 `repair.json`：

1. `red_before_repair.exit_code=1`：证明原始泄漏测试确实失败。
2. `agent_run.tool_called=true`：Qwen3 先读取源码与不可修改的测试。
3. `repair.patch`：只增加锁内原地裁剪 `del _seen_product_ids[:-500]`。
4. `green_after_repair.exit_code=0` 与 `compile.exit_code=0`：修复后测试和语法门禁通过。
5. `docker_build.exit_code=0`：修复源码可构建为镜像。
6. `docker_runtime.health=ok`、`seen_products=500`：真实容器运行正常，后台负载下状态保持有界。
7. `canonical_fixture_modified=false`：原始故障代码未改变，可以重复演示。

## 下一步开发优先级

1. 配置自己的 GitHub 演示仓与 fork；把通过门禁的补丁推送到临时分支并创建 PR。凭证不要写进仓库或 clone URL。
2. 增加失败样本、未授权目标样本和多次运行的评测数据；只有统计完成后才写简历成果数字。
3. 最后再扩展 Milvus、Jaeger、更多故障场景和 kind 后端。

"""评分卡复验能力端到端校验（核验码 258e94b9 主业务）。

直接驱动 Service 层与内存仓库，覆盖：
- 258e94b9：阈值驱动复验、明细落库、批次归档、唯一结果提交
- 2570c9b2：评分卡空态与暂无数据
- 失败重试与异常说明
- 251069f7：复验完成后刷新视图（259c2359），再回业务列表检查关联项（257abaa0）
- SCOR-0003 契约验证：阈值、基线版本、特征偏移、评分稳定性、检测中不可引用

运行：backend/.venv/bin/python -I /workspace/tests/verify_revalidation.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/workspace/backend")

from app.main import app  # noqa: E402  导入即触发 bootstrap_seed()
from app.services.datadrift import DatadriftService  # noqa: E402
from app.services.revalidation import (  # noqa: E402
    FEATURE_SHIFT_THRESHOLD,
    SCORE_STABILITY_THRESHOLD,
    RevalidationService,
)
from app.services.scorecard import ScorecardService  # noqa: E402
from app.store import store  # noqa: E402

PASS = "通过"
FAIL = "失败"
results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((PASS if condition else FAIL, name, detail))


svc = RevalidationService()
scorecard_svc = ScorecardService()
drift_svc = DatadriftService()

# ------------------------------------------------ 1. 首次复验明细与批次归档
datasets = store.rows("revalidation_datasets")
m01 = next(row for row in datasets if row["数据集编号"] == "MSET-M01")
m02 = next(row for row in datasets if row["数据集编号"] == "MSET-M02")
m03 = next(row for row in datasets if row["数据集编号"] == "MSET-M03")
details_m01 = [r for r in store.rows("revalidation_details") if r["数据集编号"] == "MSET-M01"]
batches_m01 = [r for r in store.rows("revalidation_batches") if r["数据集编号"] == "MSET-M01"]

check("258e94b9 首次形成复验明细数据集（两个基线两套判断）", len(details_m01) == 2)
check("258e94b9 明细按处理批次归档", len(batches_m01) == 1 and batches_m01[0]["明细条数"] == 2)
check("258e94b9 批次号可追溯", all(r["批次号"] == batches_m01[0]["批次号"] for r in details_m01))

# 每个明细都同时落了漂移告警与评分稳定性
check(
    "258e94b9 漂移告警与评分稳定性一并落库",
    all(("漂移告警" in r and "稳定性结论" in r) for r in details_m01),
)

# ------------------------------------------------ 2. 两套基线结论不同
fixed = next(r for r in details_m01 if r["基线类型"] == "固定观察窗口")
batch = next(r for r in details_m01 if r["基线类型"] == "最近完整批次")
check(
    "258e94b9 固定窗口基线与最近批次基线结论不同",
    fixed["稳定性结论"] != batch["稳定性结论"],
    f"固定窗口={fixed['稳定性结论']}(PSI {fixed['评分PSI']})，最近批次={batch['稳定性结论']}(PSI {batch['评分PSI']})",
)
check(
    "258e94b9 超阈值数据集不得保持稳定结论",
    (not batch["漂移告警"]) or batch["稳定性结论"] == "不稳定",
)
check(
    "258e94b9 最近批次基线存在显著特征偏移",
    any(f["偏移等级"] == "显著漂移" for f in batch["特征偏移明细"]),
    str([(f["特征"], f["特征PSI"], f["偏移等级"]) for f in batch["特征偏移明细"]]),
)
check(
    "258e94b9 评分卡只能引用一个当前基线",
    sum(1 for r in details_m01 if r["是否当前基线"]) == 1
    and fixed["是否当前基线"] is True,
)
check(
    "258e94b9 当前基线选择固定观察窗口",
    m01["当前基线版本"] == "BASE-FIX-2026Q3",
)

# ------------------------------------------------ 3. 检测中数据集不可引用
view_m02 = svc.current_baseline_view("MSET-M02")
check("258e94b9 检测中数据集不能作为评分卡当前依据", view_m02["可用"] is False, view_m02["message"])
entry, msg = svc.run_revalidation(int(m02["id"]))
check("258e94b9 检测中数据集拒绝执行复验", entry is None or entry.get("状态") == "检测中", msg)
entry, msg = svc.submit_result(int(m02["id"]))
check("258e94b9 检测中数据集拒绝提交", entry is None, msg)

# ------------------------------------------------ 4. 失败、异常与重试
check("258e94b9 异常数据集保留异常说明", m03["状态"] == "失败" and bool(m03["异常说明"]))
entry, msg = svc.submit_result(int(m03["id"]))
check("258e94b9 失败数据集无明细不可提交", entry is None, msg)
entry, msg = svc.run_revalidation(int(m03["id"]))
check("258e94b9 失败数据集未重试前拒绝复验", entry is None, msg)
view_m03 = svc.current_baseline_view("MSET-M03")
check("258e94b9 失败数据集不能作为评分卡当前依据", view_m03["可用"] is False, view_m03["message"])
baselines_before = len(svc.list_baselines("MSET-M03"))
retry_before = m03["重试次数"]
# 用仍非法的数据重试：仍失败，重试次数累加
bad_records = [
    {"特征": "收入水平", "分箱": "低", "基线占比": 0.28, "当前占比": 0.26},
    {"特征": "收入水平", "分箱": "中", "基线占比": 0.45, "当前占比": 0.40},
    {"特征": "收入水平", "分箱": "高", "基线占比": 0.27, "当前占比": 0.24},
]
entry, msg = svc.retry_dataset(int(m03["id"]), {"特征记录": bad_records})
check("258e94b9 失败重试非法数据仍被拦截并说明原因", entry["状态"] == "失败", msg)
check("258e94b9 重试次数累加", entry["重试次数"] == retry_before + 1)
# 用修正后的合法数据重试：恢复待处理，再复验成功
good_records = [
    {"特征": "收入水平", "分箱": "低", "基线占比": 0.30, "当前占比": 0.31},
    {"特征": "收入水平", "分箱": "中", "基线占比": 0.45, "当前占比": 0.44},
    {"特征": "收入水平", "分箱": "高", "基线占比": 0.25, "当前占比": 0.25},
]
entry, msg = svc.retry_dataset(int(m03["id"]), {"特征记录": good_records})
check("258e94b9 修正后重试恢复待处理", entry["状态"] == "待处理", msg)
entry, msg = svc.run_revalidation(int(m03["id"]))
check("258e94b9 重试后复验成功并归档新批次", entry["状态"] == "已完成", msg)
check(
    "258e94b9 重试复用原基线不产生重复基线",
    len(svc.list_baselines("MSET-M03")) == baselines_before,
)

# ------------------------------------------------ 5. 新链路接收：缺字段/空记录
entry, msg = svc.ingest_monitoring_dataset({"数据集编号": "MSET-X1"})
check("258e94b9 接收缺字段给出说明", entry is None, msg)
entry, msg = svc.ingest_monitoring_dataset(
    {
        "数据集编号": "MSET-X2",
        "监控数据集": "空记录数据集",
        "评分编号": "SCOR-0003",
        "特征记录": [],
    }
)
check("258e94b9 空特征记录接收失败可重试", entry is None or entry["状态"] == "失败", msg)

# ------------------------------------------------ 6. 唯一可用结果提交（幂等）
entry, msg1 = svc.submit_result(int(m01["id"]))
check("258e94b9 提交只接收含明细的唯一可用结果", entry["提交状态"] == "已提交", msg1)
entry, msg2 = svc.submit_result(int(m01["id"]))
check("258e94b9 重复提交幂等", entry["提交状态"] == "已提交" and "已提交" in msg2, msg2)

# ------------------------------------------------ 7. 评分卡详情与空态（2570c9b2）
scor3 = next(row for row in store.rows("scorecard") if row["评分编号"] == "SCOR-0003")
detail_view = scorecard_svc.get_entry(int(scor3["id"]))
check(
    "2570c9b2 评分卡详情展示漂移告警/稳定性/特征偏移",
    "当前复验结论" in detail_view
    and {"漂移告警", "稳定性结论", "特征偏移明细"} <= set(detail_view["当前复验结论"]),
)
check("2570c9b2 详情读取同一监控数据集", len(detail_view["关联监控数据集"]) >= 2)
# 空态评分卡（SCOR-0001 无复验数据）
scor1 = next(row for row in store.rows("scorecard") if row["评分编号"] == "SCOR-0001")
empty_view = scorecard_svc.get_entry(int(scor1["id"]))
check("2570c9b2 无复验数据时空态有明确说明", "复验空态说明" in empty_view and "暂无数据" in empty_view["复验空态说明"])
empty_rows, empty_total = scorecard_svc.list_entries(keyword="SCOR-0001")
check("2570c9b2 列表空态字段为暂无数据", empty_rows[0]["评分稳定性"] == "暂无数据")

# ------------------------------------------------ 8. 数据漂移清单同步
drift_rows, _ = drift_svc.list_entries(page=1, size=100)
d1 = next(r for r in drift_rows if r["关联数据集编号"] == "MSET-M01")
check(
    "258e94b9 SCOR-0003 结论同步到数据漂移清单",
    d1.get("关联评分卡") == "SCOR-0003"
    and d1.get("漂移告警") == fixed["漂移告警"]
    and d1.get("评分稳定性") == fixed["稳定性结论"]
    and d1.get("复验批次号") == fixed["批次号"],
)
d2 = next(r for r in drift_rows if r["关联数据集编号"] == "MSET-M02")
check("258e94b9 检测中数据集在漂移清单标注检测中", d2.get("复验接收状态") == "检测中")

# ------------------------------------------------ 9. 契约验证样本
contract = svc.contract_check("SCOR-0003")
check("SCOR-0003 契约验证样本全部核验项通过", contract["全部通过"], str([c["核验项"] for c in contract["核验项"] if not c["通过"]]))
check("SCOR-0003 阈值核对（特征0.10/评分0.10）", FEATURE_SHIFT_THRESHOLD == 0.10 and SCORE_STABILITY_THRESHOLD == 0.10)

# ------------------------------------------------ 10. 视图刷新与列表关联（259c2359 / 257abaa0）
# 模拟“完成后刷新视图”：重新读取即拿到最新落库结论
refreshed = scorecard_svc.get_entry(int(scor3["id"]))
check("259c2359 复验完成后刷新视图拿到最新结论", refreshed["当前复验结论"]["批次号"] == fixed["批次号"])
# 回到业务列表检查关联项
sc_list, _ = scorecard_svc.list_entries(page=1, size=100)
sc3_row = next(r for r in sc_list if r["评分编号"] == "SCOR-0003")
check(
    "257abaa0 业务列表可检查关联项（告警/稳定性/当前基线/批次）",
    sc3_row["复验状态"] == "已复验"
    and sc3_row["当前基线版本"] == "BASE-FIX-2026Q3"
    and "复验批次号" in sc3_row,
)

# ------------------------------------------------ 汇总输出
width = max(len(name) for _, name, _ in results)
failed = 0
for status, name, detail in results:
    if status == FAIL:
        failed += 1
    print(f"[{status}] {name.ljust(width)}  {detail}")
print(f"\n共 {len(results)} 项，失败 {failed} 项")
sys.exit(1 if failed else 0)

"""数据漂移业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "datadrift"
REQUIRED_FIELDS = ["检测编号", "监控数据集", "基线版本"]
STATUS_ORDER = ["草稿", "规则评审中", "已启用", "已关闭"]
ACTION_RULES = {"提交规则评审": "规则评审中", "启用检测": "已启用", "关闭检测": "已关闭"}
NEGATIVE_ACTIONS = []

# 预置漂移检测与复验监控数据集的映射：SCOR-0003 结论同步到数据漂移清单
DATASET_LINK = {
    "数据漂移样例1": ("MSET-M01", "申请评分监控数据集-2026W44", "SCOR-0003"),
    "数据漂移样例2": ("MSET-M02", "申请评分监控数据集-2026W45", "SCOR-0003"),
    "数据漂移样例3": ("MSET-M03", "申请评分监控数据集-2026W46", "SCOR-0003"),
}


class DatadriftService:
    def _hydrate(self, row: dict[str, Any]) -> dict[str, Any]:
        """把评分卡复验结论同步到漂移清单；未落库的预置数据在此兜底关联。"""
        if "关联数据集编号" not in row:
            link = DATASET_LINK.get(str(row.get("监控数据集")))
            if link is not None:
                row["关联数据集编号"], row["监控数据集全名"], row["关联评分卡"] = link
            else:
                row["关联数据集编号"] = ""
                row["监控数据集全名"] = row.get("监控数据集", "")
                row["关联评分卡"] = ""
        code = row.get("关联数据集编号")
        if code:
            dataset = next(
                (item for item in store.rows("revalidation_datasets") if item.get("数据集编号") == code),
                None,
            )
            if dataset is not None:
                row["复验接收状态"] = dataset.get("状态")
                row["提交状态"] = dataset.get("提交状态")
                details = [
                    item
                    for item in store.rows("revalidation_details")
                    if item.get("数据集编号") == code and item.get("是否当前基线")
                ]
                if details:
                    current = details[0]
                    row["当前基线版本"] = current.get("基线版本")
                    row["漂移告警"] = current.get("漂移告警")
                    row["评分稳定性"] = current.get("稳定性结论")
                    row["最近漂移值"] = current.get("评分PSI")
                    row["复验批次号"] = current.get("批次号")
                    row["待处理明细"] = "评分卡复验明细数据集已接收"
                else:
                    row.setdefault("漂移告警", None)
                    row.setdefault("评分稳定性", "暂无数据" if dataset.get("状态") != "检测中" else "检测中")
                    row.setdefault("待处理明细", dataset.get("异常说明") or "等待评分卡复验明细数据集")
        return row

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("检测编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        enriched = [self._hydrate(dict(row)) for row in rows]
        return enriched[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self._hydrate(dict(entry))

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"漂移检测 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据漂移可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"漂移检测已{action}"

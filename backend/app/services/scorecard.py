"""评分卡业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.services.revalidation import RevalidationService
from app.store import store

MODULE = "scorecard"
REQUIRED_FIELDS = ["评分编号", "评分对象", "特征变量组"]
STATUS_ORDER = ["草稿", "评分校验中", "已启用", "已废弃"]
ACTION_RULES = {"提交评分校验": "评分校验中", "启用评分": "已启用", "废弃评分": "已废弃"}
NEGATIVE_ACTIONS = []

revalidation_service = RevalidationService()


class ScorecardService:
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
            rows = [row for row in rows if keyword in str(row.get("评分编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        # 列表同步数据漂移驱动的复验结论（核验码 257abaa0：关联项可在业务列表检查）
        enriched = [self._with_revalidation_summary(dict(row)) for row in rows]
        return enriched[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self._with_revalidation_view(dict(entry))

    def _with_revalidation_summary(self, entry: dict[str, Any]) -> dict[str, Any]:
        """列表行附带当前基线下的漂移告警与稳定性结论（空态给出暂无数据说明）。"""
        code = str(entry.get("评分编号", ""))
        details, total = revalidation_service.list_details(
            scorecard_code=code, current_only=True, page=1, size=100
        )
        if total == 0:
            entry["复验状态"] = "暂无复验数据"
            entry["漂移告警"] = None
            entry["评分稳定性"] = "暂无数据"
            entry["当前基线版本"] = ""
            return entry
        current = details[0]
        entry["复验状态"] = "已复验"
        entry["漂移告警"] = current.get("漂移告警")
        entry["评分稳定性"] = current.get("稳定性结论")
        entry["当前基线版本"] = current.get("基线版本")
        entry["复验批次号"] = current.get("批次号")
        return entry

    def _with_revalidation_view(self, entry: dict[str, Any]) -> dict[str, Any]:
        """评分卡详情读取同一监控数据集，展示漂移告警、稳定性结论和特征偏移。"""
        code = str(entry.get("评分编号", ""))
        details, total = revalidation_service.list_details(
            scorecard_code=code, page=1, size=100
        )
        datasets = [
            row
            for row in store.rows("revalidation_datasets")
            if row.get("评分编号") == code
        ]
        entry["复验明细数据集"] = details
        entry["关联监控数据集"] = [
            {
                "数据集编号": row.get("数据集编号"),
                "监控数据集": row.get("监控数据集"),
                "状态": row.get("状态"),
                "当前基线版本": row.get("当前基线版本"),
                "提交状态": row.get("提交状态"),
            }
            for row in datasets
        ]
        if total == 0:
            entry["复验空态说明"] = "暂无数据：该评分卡尚未接收到数据漂移驱动的复验明细数据集"
        current = next((row for row in details if row.get("是否当前基线")), None)
        if current is not None:
            entry["当前复验结论"] = {
                "监控数据集": current.get("监控数据集"),
                "数据集编号": current.get("数据集编号"),
                "基线版本": current.get("基线版本"),
                "基线类型": current.get("基线类型"),
                "漂移告警": current.get("漂移告警"),
                "稳定性结论": current.get("稳定性结论"),
                "评分PSI": current.get("评分PSI"),
                "评分稳定阈值": current.get("评分稳定阈值"),
                "偏移特征": current.get("偏移特征"),
                "特征偏移明细": current.get("特征偏移明细"),
                "批次号": current.get("批次号"),
            }
        return entry

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
            return None, f"评分卡 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于评分卡可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"评分卡已{action}"

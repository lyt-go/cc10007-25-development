"""评分卡复验业务规则（核验码 258e94b9）。

新链路（供新能力）把“漂移检测监控数据集 + 评分卡特征记录”推送到本服务后：

1. ingest_monitoring_dataset 接收并校验监控数据集（失败可重试，核验码 258e94b9-异常）；
2. run_revalidation 按新链路读取监控数据集，对每个【可用基线版本】计算 PSI、
   特征偏移与评分稳定性，首次生成“评分卡复验明细数据集”，并按处理批次归档；
3. 漂移告警与评分稳定性一并落库；超过阈值的数据集不能保持稳定结论；
4. submit_result 只接收“含评分卡复验明细数据集”的唯一可用结果（幂等）；
5. 同一监控数据集存在两个可用基线时会得到两套漂移判断，评分卡只能引用一个
   当前基线（固定观察窗口优先于最近完整批次），仍在检测中的数据集/基线不得引用。
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from app.seed_extra import (
    FEATURE_SHIFT_THRESHOLD,
    SCORE_STABILITY_THRESHOLD,
    SIGNIFICANT_DRIFT_THRESHOLD,
)
from app.store import store

MODULE_DATASET = "revalidation_datasets"
MODULE_BASELINE = "revalidation_baselines"
MODULE_BATCH = "revalidation_batches"
MODULE_DETAIL = "revalidation_details"

# 基线类型优先级：固定观察窗口 > 最近完整批次（同数据集只允许一个当前基线）
BASELINE_PRIORITY = {"固定观察窗口": 0, "最近完整批次": 1}

DATASET_STATUSES = ["待处理", "检测中", "已完成", "失败"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _round(value: float) -> float:
    return round(float(value), 4)


def _psi(p_base: float, p_curr: float) -> float:
    """单分箱 PSI 分量；占比为 0 时用极小值平滑，避免取对数失败。"""
    eps = 1e-6
    b = max(float(p_base), eps)
    c = max(float(p_curr), eps)
    return (c - b) * math.log(c / b)


def _feature_psi(records: list[dict[str, Any]]) -> tuple[float, list[dict[str, Any]]]:
    """按特征汇总各分箱 PSI，并返回逐特征明细（含是否超阈值与偏移等级）。"""
    grouped: dict[str, float] = {}
    for record in records:
        feature = str(record.get("特征") or "")
        grouped[feature] = grouped.get(feature, 0.0) + _psi(
            record.get("基线占比", 0.0), record.get("当前占比", 0.0)
        )
    feature_rows: list[dict[str, Any]] = []
    for feature, psi_value in grouped.items():
        psi_value = _round(psi_value)
        if psi_value >= SIGNIFICANT_DRIFT_THRESHOLD:
            level = "显著漂移"
            shifted = True
        elif psi_value >= FEATURE_SHIFT_THRESHOLD:
            level = "偏移预警"
            shifted = True
        else:
            level = "稳定"
            shifted = False
        feature_rows.append(
            {
                "特征": feature,
                "特征PSI": psi_value,
                "偏移阈值": FEATURE_SHIFT_THRESHOLD,
                "显著漂移阈值": SIGNIFICANT_DRIFT_THRESHOLD,
                "是否偏移": shifted,
                "偏移等级": level,
            }
        )
    score_psi = _round(sum(grouped.values()) / len(grouped)) if grouped else 0.0
    return score_psi, feature_rows


class RevalidationService:
    # ------------------------------------------------------------------ 读取
    def list_datasets(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE_DATASET)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("数据集编号", ""))
                or keyword in str(row.get("监控数据集", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("状态") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_dataset(self, dataset_id: int) -> dict[str, Any] | None:
        return store.find(MODULE_DATASET, dataset_id)

    def find_dataset_by_code(self, dataset_code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE_DATASET):
            if str(row.get("数据集编号")) == dataset_code:
                return row
        return None

    def list_baselines(self, dataset_code: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(MODULE_BASELINE)
        if dataset_code:
            rows = [row for row in rows if row.get("数据集编号") == dataset_code]
        return rows

    def list_batches(self, dataset_code: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(MODULE_BATCH)
        if dataset_code:
            rows = [row for row in rows if row.get("数据集编号") == dataset_code]
        return rows

    def list_details(
        self,
        *,
        dataset_code: str | None = None,
        scorecard_code: str | None = None,
        current_only: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE_DETAIL)
        if dataset_code:
            rows = [row for row in rows if row.get("数据集编号") == dataset_code]
        if scorecard_code:
            rows = [row for row in rows if row.get("评分编号") == scorecard_code]
        if current_only:
            rows = [row for row in rows if row.get("是否当前基线")]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    # ---------------------------------------------------------- 当前基线选择
    def _available_baselines(self, dataset_code: str) -> list[dict[str, Any]]:
        """只有状态为“已完成”的基线可参与判断；检测中的基线必须排除。"""
        return [
            row
            for row in self.list_baselines(dataset_code)
            if row.get("状态") == "已完成"
        ]

    def pick_current_baseline(self, dataset_code: str) -> dict[str, Any] | None:
        """同一监控数据集只允许一个当前基线：固定观察窗口优先，其次最近完整批次。"""
        candidates = sorted(
            self._available_baselines(dataset_code),
            key=lambda row: (
                BASELINE_PRIORITY.get(str(row.get("基线类型")), 99),
                int(row.get("id", 0)),
            ),
        )
        return candidates[0] if candidates else None

    def current_baseline_view(self, dataset_code: str) -> dict[str, Any]:
        dataset = self.find_dataset_by_code(dataset_code)
        if dataset is None:
            return {
                "数据集编号": dataset_code,
                "可用": False,
                "message": f"监控数据集 {dataset_code} 不存在或已归档",
            }
        if dataset.get("状态") == "检测中":
            return {
                "数据集编号": dataset_code,
                "可用": False,
                "message": "监控数据集仍在检测中，评分卡不能引用为当前依据",
            }
        if dataset.get("状态") == "失败":
            return {
                "数据集编号": dataset_code,
                "可用": False,
                "message": "监控数据集接收校验失败，评分卡不能引用为当前依据，请先修正并重试",
            }
        current = self.pick_current_baseline(dataset_code)
        if current is None:
            return {
                "数据集编号": dataset_code,
                "可用": False,
                "message": "没有可用（已完成）基线版本，评分卡暂无当前基线可引用",
            }
        return {
            "数据集编号": dataset_code,
            "可用": True,
            "当前基线版本": current.get("基线版本"),
            "基线类型": current.get("基线类型"),
            "候选基线数": len(self._available_baselines(dataset_code)),
            "message": "当前基线已按“固定观察窗口优先、最近完整批次其次”确定",
        }

    # ------------------------------------------------------------ 接收监控数据集
    def ingest_monitoring_dataset(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """接收供新能力推送的监控数据集与评分卡特征记录（新链路）。

        校验失败不静默丢弃：数据集落为“失败”并写明异常说明，允许修正后重试。
        """
        required = ["数据集编号", "监控数据集", "评分编号", "特征记录"]
        missing = [field for field in required if not values.get(field)]
        if missing:
            return None, f"接收失败，缺少必填字段：{'、'.join(missing)}"

        dataset_code = str(values["数据集编号"]).strip()
        records = values.get("特征记录") or []
        error = self._validate_records(records)
        rows = store.rows(MODULE_DATASET)
        existing = self.find_dataset_by_code(dataset_code)

        if error:
            if existing is not None:
                existing["状态"] = "失败"
                existing["重试次数"] = int(existing.get("重试次数", 0)) + 1
                existing["异常说明"] = error
                existing["提交状态"] = "未提交"
                return existing, f"监控数据集 {dataset_code} 校验未通过：{error}，可修正后重试"
            entry = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "数据集编号": dataset_code,
                "监控数据集": str(values["监控数据集"]).strip(),
                "接收时间": _now(),
                "来源链路": str(values.get("来源链路") or "供新能力-漂移检测监控链路"),
                "观察窗口": str(values.get("观察窗口") or "近30天"),
                "评分编号": str(values["评分编号"]).strip(),
                "状态": "失败",
                "重试次数": 1,
                "异常说明": error,
                "提交状态": "未提交",
                "当前基线版本": "",
            }
            rows.append(entry)
            return entry, f"监控数据集 {dataset_code} 校验未通过：{error}，可修正后重试"

        # 校验通过：新建或重置数据集，并落一条待复验基线（固定观察窗口口径）
        if existing is None:
            entry = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "数据集编号": dataset_code,
                "监控数据集": str(values["监控数据集"]).strip(),
                "接收时间": _now(),
                "来源链路": str(values.get("来源链路") or "供新能力-漂移检测监控链路"),
                "观察窗口": str(values.get("观察窗口") or "近30天"),
                "评分编号": str(values["评分编号"]).strip(),
                "状态": "待处理",
                "重试次数": 0,
                "异常说明": "",
                "提交状态": "未提交",
                "当前基线版本": "",
            }
            rows.append(entry)
        else:
            entry = existing
            entry["状态"] = "待处理"
            entry["异常说明"] = ""
            entry["提交状态"] = "未提交"
            entry["接收时间"] = _now()

        baseline_rows = store.rows(MODULE_BASELINE)
        baseline_code = str(values.get("基线版本") or f"BASE-FIX-{dataset_code}")
        baseline = next(
            (
                row
                for row in baseline_rows
                if row.get("数据集编号") == dataset_code and row.get("基线版本") == baseline_code
            ),
            None,
        )
        clean_records = [dict(record) for record in records]
        if baseline is None:
            baseline = {
                "id": max((int(row.get("id", 0)) for row in baseline_rows), default=0) + 1,
                "数据集编号": dataset_code,
                "基线版本": baseline_code,
                "基线类型": str(values.get("基线类型") or "固定观察窗口"),
                "状态": "已完成",
                "观察窗口说明": str(values.get("观察窗口说明") or entry.get("观察窗口") or ""),
                "特征记录": clean_records,
            }
            baseline_rows.append(baseline)
        else:
            baseline["特征记录"] = clean_records
            baseline["状态"] = "已完成"
        return entry, f"监控数据集 {dataset_code} 已接收，等待触发评分卡复验"

    @staticmethod
    def _validate_records(records: Any) -> str:
        if not isinstance(records, list) or not records:
            return "特征记录为空，无法计算评分稳定性"
        grouped: dict[str, tuple[float, float]] = {}
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                return f"第{index}条特征记录格式不正确"
            for key in ("特征", "分箱", "基线占比", "当前占比"):
                if record.get(key) in (None, ""):
                    return f"第{index}条特征记录缺少字段「{key}」"
            try:
                base = float(record["基线占比"])
                curr = float(record["当前占比"])
            except (TypeError, ValueError):
                return f"第{index}条特征记录占比不是数值"
            if base < 0 or curr < 0:
                return f"第{index}条特征记录占比不能为负"
            feature = str(record["特征"])
            b0, c0 = grouped.get(feature, (0.0, 0.0))
            grouped[feature] = (b0 + base, c0 + curr)
        for feature, (base_sum, curr_sum) in grouped.items():
            if abs(base_sum - 1.0) > 0.02 or abs(curr_sum - 1.0) > 0.02:
                return (
                    f"特征「{feature}」分箱占比之和不为1"
                    f"（基线{_round(base_sum)}、当前{_round(curr_sum)}）"
                )
        return ""

    # ------------------------------------------------------------ 失败重试
    def retry_dataset(self, dataset_id: int, values: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
        """失败重试（核验码 258e94b9-失败重试）：允许携带修正后的特征记录重新接收。"""
        dataset = store.find(MODULE_DATASET, dataset_id)
        if dataset is None:
            return None, f"监控数据集 {dataset_id} 不存在或已归档"
        if dataset.get("状态") != "失败":
            return None, f"监控数据集 {dataset.get('数据集编号')} 当前为「{dataset.get('状态')}」，无需重试"
        if values and values.get("特征记录"):
            # 复用数据集已有基线，修正其特征记录，避免同一数据集出现重复基线
            existing_baseline = next(
                iter(self.list_baselines(str(dataset.get("数据集编号")))),
                None,
            )
            payload = {
                "数据集编号": dataset.get("数据集编号"),
                "监控数据集": dataset.get("监控数据集"),
                "评分编号": dataset.get("评分编号"),
                "观察窗口": dataset.get("观察窗口"),
                "特征记录": values.get("特征记录"),
                "基线版本": (
                    values.get("基线版本")
                    or (existing_baseline or {}).get("基线版本")
                ),
                "基线类型": (
                    values.get("基线类型")
                    or (existing_baseline or {}).get("基线类型")
                ),
            }
            entry, message = self.ingest_monitoring_dataset(payload)
            if entry is None or entry.get("状态") == "失败":
                return entry, message
            return entry, f"重试成功：{message}"
        # 未提供修正数据时，仅把历史失败重新置为待处理（由后续复验重新计算）
        dataset["状态"] = "待处理"
        dataset["异常说明"] = ""
        return dataset, f"监控数据集 {dataset.get('数据集编号')} 已重新排队，等待复验"

    # ------------------------------------------------------------ 执行复验
    def run_revalidation(self, dataset_id: int) -> tuple[dict[str, Any] | None, str]:
        """读取同一监控数据集并对每个可用基线计算，生成复验明细并按批次归档。"""
        dataset = store.find(MODULE_DATASET, dataset_id)
        if dataset is None:
            return None, f"监控数据集 {dataset_id} 不存在或已归档"
        dataset_code = str(dataset.get("数据集编号"))
        if dataset.get("状态") == "检测中":
            return None, "监控数据集仍在检测中，评分卡不能引用为当前依据，请等待检测完成"
        if dataset.get("状态") == "失败":
            return None, "监控数据集接收校验未通过，请先修正特征记录并重试，再执行评分卡复验"

        baselines = self._available_baselines(dataset_code)
        if not baselines:
            dataset["状态"] = "失败"
            dataset["异常说明"] = "没有可用（已完成）基线版本，无法计算评分稳定性"
            return dataset, "复验失败：没有可用基线版本"

        # 处理批次归档：同一数据集重复复验生成新批次，明细按批次号关联
        batch_rows = store.rows(MODULE_BATCH)
        batch_no = f"BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}-{dataset_id}"
        batch = {
            "id": max((int(row.get("id", 0)) for row in batch_rows), default=0) + 1,
            "批次号": batch_no,
            "数据集编号": dataset_code,
            "评分编号": dataset.get("评分编号"),
            "处理时间": _now(),
            "基线版本数": len(baselines),
            "明细条数": 0,
            "状态": "处理中",
        }
        batch_rows.append(batch)

        current_baseline = self.pick_current_baseline(dataset_code)
        detail_rows = store.rows(MODULE_DETAIL)
        produced: list[dict[str, Any]] = []
        any_alert = False
        for baseline in baselines:
            score_psi, feature_rows = _feature_psi(baseline.get("特征记录") or [])
            shifted_features = [row["特征"] for row in feature_rows if row["是否偏移"]]
            alert = bool(shifted_features) or score_psi >= SCORE_STABILITY_THRESHOLD
            any_alert = any_alert or alert
            # 超过阈值的数据集不能继续保持稳定结论
            stability = "不稳定" if alert else "稳定"
            is_current = current_baseline is not None and baseline.get("id") == current_baseline.get("id")
            detail = {
                "id": max((int(row.get("id", 0)) for row in detail_rows), default=0) + 1,
                "明细编号": f"RVAL-{dataset_code}-{baseline.get('基线版本')}",
                "批次号": batch_no,
                "数据集编号": dataset_code,
                "监控数据集": dataset.get("监控数据集"),
                "评分编号": dataset.get("评分编号"),
                "基线版本": baseline.get("基线版本"),
                "基线类型": baseline.get("基线类型"),
                "是否当前基线": is_current,
                "特征偏移明细": feature_rows,
                "偏移特征数": len(shifted_features),
                "偏移特征": "、".join(shifted_features),
                "评分PSI": score_psi,
                "评分稳定阈值": SCORE_STABILITY_THRESHOLD,
                "漂移告警": alert,
                "告警说明": (
                    "超过阈值，触发漂移告警，评分稳定性结论不成立"
                    if alert
                    else "各项指标均在阈值内，未触发漂移告警"
                ),
                "稳定性结论": stability,
                "复验时间": _now(),
            }
            detail_rows.append(detail)
            produced.append(detail)

        batch["明细条数"] = len(produced)
        batch["状态"] = "已归档"
        dataset["状态"] = "已完成"
        dataset["异常说明"] = ""
        dataset["当前基线版本"] = current_baseline.get("基线版本") if current_baseline else ""
        # 评分卡（SCOR-0003）结论同步到数据漂移清单
        self._sync_datadrift(dataset, produced, any_alert)
        return dataset, (
            f"复验完成：批次 {batch_no} 归档 {len(produced)} 条评分卡复验明细，"
            f"当前基线为 {dataset['当前基线版本']}，"
            f"{'存在漂移告警' if any_alert else '未触发漂移告警'}"
        )

    # ------------------------------------------------------------ 结果提交
    def submit_result(self, dataset_id: int) -> tuple[dict[str, Any] | None, str]:
        """只接收含评分卡复验明细数据集的唯一可用结果，重复提交幂等。"""
        dataset = store.find(MODULE_DATASET, dataset_id)
        if dataset is None:
            return None, f"监控数据集 {dataset_id} 不存在或已归档"
        if dataset.get("状态") == "检测中":
            return None, "监控数据集仍在检测中，不能提交复验结果"
        if dataset.get("状态") == "失败":
            return None, "监控数据集复验失败，未形成复验明细数据集，请先修正并重试"
        details = [
            row
            for row in store.rows(MODULE_DETAIL)
            if row.get("数据集编号") == dataset.get("数据集编号")
        ]
        if not details:
            return None, "未找到评分卡复验明细数据集，不能提交空结果"
        if dataset.get("提交状态") == "已提交":
            return dataset, "该复验明细数据集已提交，结果唯一可用，无需重复提交"
        dataset["提交状态"] = "已提交"
        dataset["提交时间"] = _now()
        current = next((row for row in details if row.get("是否当前基线")), details[0])
        return dataset, (
            f"提交成功：接收评分卡复验明细数据集（{len(details)} 条，"
            f"当前基线 {current.get('基线版本')}，结论 {current.get('稳定性结论')}）"
        )

    # ----------------------------------------------------- 同步到数据漂移清单
    @staticmethod
    def _sync_datadrift(
        dataset: dict[str, Any],
        details: list[dict[str, Any]],
        any_alert: bool,
    ) -> None:
        """把当前基线下的漂移告警与稳定性结论回写到数据漂移待处理明细。"""
        current = next((row for row in details if row.get("是否当前基线")), None)
        for drift in store.rows("datadrift"):
            if drift.get("监控数据集") != dataset.get("监控数据集"):
                continue
            drift["关联数据集编号"] = dataset.get("数据集编号")
            drift["关联评分卡"] = dataset.get("评分编号")
            drift["当前基线版本"] = (current or {}).get("基线版本", dataset.get("当前基线版本", ""))
            drift["漂移告警"] = any_alert
            drift["评分稳定性"] = (current or {}).get("稳定性结论", "")
            drift["最近漂移值"] = (current or {}).get("评分PSI", drift.get("最近漂移值"))
            drift["复验批次号"] = (current or {}).get("批次号", "")
            drift["待处理明细"] = "评分卡复验明细数据集已接收"

    # ----------------------------------------------------- SCOR-0003 契约验证
    def contract_check(self, scorecard_code: str = "SCOR-0003") -> dict[str, Any]:
        """SCOR-0003 契约验证样本：核对阈值、基线版本、特征偏移与评分稳定性。"""
        details = [
            row
            for row in store.rows(MODULE_DETAIL)
            if row.get("评分编号") == scorecard_code
        ]
        current = next((row for row in details if row.get("是否当前基线")), None)
        scorecard = next(
            (row for row in store.rows("scorecard") if row.get("评分编号") == scorecard_code),
            None,
        )
        # 当前基线唯一性按“监控数据集”维度校验：同一数据集至多一个当前基线
        current_per_dataset: dict[str, int] = {}
        for row in details:
            if row.get("是否当前基线"):
                code = str(row.get("数据集编号"))
                current_per_dataset[code] = current_per_dataset.get(code, 0) + 1
        unique_current = all(count == 1 for count in current_per_dataset.values())
        checks = [
            {
                "核验项": "阈值口径",
                "通过": SCORE_STABILITY_THRESHOLD == 0.10 and FEATURE_SHIFT_THRESHOLD == 0.10,
                "说明": (
                    f"特征偏移阈值 {FEATURE_SHIFT_THRESHOLD}、"
                    f"评分稳定阈值 {SCORE_STABILITY_THRESHOLD}"
                ),
            },
            {
                "核验项": "基线版本唯一",
                "通过": current is not None and unique_current,
                "说明": (
                    f"当前基线 {current.get('基线版本')}（{current.get('基线类型')}）；"
                    f"各监控数据集当前基线数 {current_per_dataset}"
                    if current
                    else "尚未确定当前基线"
                ),
            },
            {
                "核验项": "检测中数据集不可引用",
                "通过": all(
                    self.find_dataset_by_code(str(row.get("数据集编号"))) is None
                    or self.find_dataset_by_code(str(row.get("数据集编号"))).get("状态") != "检测中"
                    for row in details
                ),
                "说明": "检测中的监控数据集不得作为评分卡当前依据",
            },
            {
                "核验项": "超阈值不得稳定",
                "通过": all(
                    (not row.get("漂移告警")) or row.get("稳定性结论") == "不稳定"
                    for row in details
                ),
                "说明": "漂移告警与评分稳定性已一并落库，超阈值结论自动判为不稳定",
            },
            {
                "核验项": "数据批次可追溯",
                "通过": all(row.get("批次号") for row in details),
                "说明": "每条复验明细均带处理批次号，可回溯到处理批次",
            },
        ]
        return {
            "核验码": "258e94b9",
            "评分编号": scorecard_code,
            "评分卡状态": (scorecard or {}).get("status"),
            "明细条数": len(details),
            "全部通过": all(item["通过"] for item in checks),
            "核验项": checks,
            "当前基线复验": current,
        }

    # ------------------------------------------------------------ 首次引导
    def bootstrap_seed(self) -> None:
        """对已完成接收的预置监控数据集首次计算，生成首批评验明细与处理批次。"""
        for dataset in list(store.rows(MODULE_DATASET)):
            if dataset.get("状态") != "待处理":
                continue
            self.run_revalidation(int(dataset["id"]))

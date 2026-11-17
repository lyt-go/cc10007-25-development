"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_ROWS
from app.seed_extra import REVALIDATION_SEED


class Store:
    def __init__(self) -> None:
        merged: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 评分卡复验领域：监控数据集、基线版本、处理批次、复验明细
        for name, rows in REVALIDATION_SEED.items():
            merged[name] = [dict(row) for row in rows]
        self._tables: dict[str, list[dict[str, Any]]] = merged

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        # 评分卡复验的内部表（监控数据集/基线/批次/明细）不单独作为业务模块展示，
        # 其结论已同步到“评分卡”和“数据漂移”两个业务模块。
        hidden = {"revalidation_datasets", "revalidation_baselines", "revalidation_batches", "revalidation_details"}
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            if name in hidden:
                continue
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()

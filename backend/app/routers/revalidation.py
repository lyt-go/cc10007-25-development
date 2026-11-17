"""评分卡复验接口（核验码 258e94b9）。

承接数据漂移“供新能力”链路推送的监控数据集与评分卡特征记录，提供：
接收/重试、复验计算（生成复验明细并按批次归档）、结果提交（唯一可用结果）、
处理批次与明细查询、SCOR-0003 契约验证、当前基线查询。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.revalidation import RevalidationService

router = APIRouter(prefix="/api/revalidation", tags=["评分卡复验"])

service = RevalidationService()


@router.get("/datasets", response_model=PageResult[dict])
def list_datasets(
    keyword: str | None = Query(default=None, description="按数据集编号或名称检索"),
    status: str | None = Query(default=None, description="待处理、检测中、已完成、失败"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """数据漂移待处理明细：接收评分卡复验明细数据集的监控数据集清单。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_datasets(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/datasets/{dataset_id}", response_model=dict)
def get_dataset(dataset_id: int) -> dict:
    """读取单个监控数据集，含同数据集下的基线版本、处理批次与复验明细。"""
    dataset = service.get_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"监控数据集 {dataset_id} 不存在或已归档")
    code = str(dataset.get("数据集编号"))
    return {
        **dataset,
        "基线版本": service.list_baselines(code),
        "处理批次": service.list_batches(code),
        "复验明细": service.list_details(dataset_code=code, page=1, size=100)[0],
        "当前基线": service.current_baseline_view(code),
    }


@router.post("/datasets", response_model=ActionResult)
def ingest_dataset(payload: EntryPayload) -> ActionResult:
    """新链路接收监控数据集与评分卡特征记录；校验失败落异常说明，可重试。"""
    entry, message = service.ingest_monitoring_dataset(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=entry.get("状态") != "失败", message=message, entry=entry)


@router.post("/datasets/{dataset_id}/retry", response_model=ActionResult)
def retry_dataset(dataset_id: int, payload: EntryPayload | None = None) -> ActionResult:
    """失败重试（核验码 258e94b9）：可携带修正后的特征记录重新接收。"""
    values = payload.values if payload is not None else None
    entry, message = service.retry_dataset(dataset_id, values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=entry.get("状态") != "失败", message=message, entry=entry)


@router.post("/datasets/{dataset_id}/revalidate", response_model=ActionResult)
def revalidate(dataset_id: int) -> ActionResult:
    """按新链路读取监控数据集并计算评分稳定性，生成复验明细并按批次归档。"""
    entry, message = service.run_revalidation(dataset_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=entry.get("状态") == "已完成", message=message, entry=entry)


@router.post("/datasets/{dataset_id}/submit", response_model=ActionResult)
def submit(dataset_id: int) -> ActionResult:
    """提交只接收含评分卡复验明细数据集的唯一可用结果（重复提交幂等）。"""
    entry, message = service.submit_result(dataset_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/details", response_model=PageResult[dict])
def list_details(
    dataset: str | None = Query(default=None, description="按监控数据集编号过滤"),
    scorecard: str | None = Query(default=None, description="按评分编号过滤，如 SCOR-0003"),
    current_only: bool = Query(default=False, description="仅看评分卡当前基线的复验明细"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """评分卡复验明细数据集：阈值、基线版本、特征偏移与评分稳定性一并落库可查。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_details(
        dataset_code=dataset,
        scorecard_code=scorecard,
        current_only=current_only,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/batches")
def list_batches(dataset: str | None = Query(default=None)) -> dict:
    """处理批次归档信息：新增数据漂移驱动的评分卡复验可从数据批次追溯。"""
    items = service.list_batches(dataset)
    return {"module": "revalidation_batches", "total": len(items), "items": items}


@router.get("/baselines")
def list_baselines(dataset: str | None = Query(default=None)) -> dict:
    """同一监控数据集的基线版本清单（含检测中、固定观察窗口、最近完整批次）。"""
    items = service.list_baselines(dataset)
    return {"module": "revalidation_baselines", "total": len(items), "items": items}


@router.get("/current-baseline")
def current_baseline(dataset: str = Query(..., description="监控数据集编号")) -> dict:
    """评分卡只能引用一个当前基线；检测中的数据集不会成为当前依据。"""
    return service.current_baseline_view(dataset)


@router.get("/contract/scor-0003")
def contract_scor_0003() -> dict:
    """SCOR-0003 契约验证样本：核对阈值、基线版本、特征偏移和评分稳定性。"""
    return service.contract_check("SCOR-0003")

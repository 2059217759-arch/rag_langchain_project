from fastapi import APIRouter, Depends, Query

from api.deps import get_current_user
from core.metrics import get_metrics_summary, get_recent_metrics

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/summary")
def metrics_summary(
    days: int = Query(default=7, ge=1, le=90),
    user: dict = Depends(get_current_user),
):
    """获取性能指标汇总。"""
    return get_metrics_summary(session_id=None, days=days)


@router.get("/recent")
def metrics_recent(
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    """获取最近的查询明细。"""
    return get_recent_metrics(session_id=None, limit=limit)

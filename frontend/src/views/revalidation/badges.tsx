/** 复验结论的统一展示：漂移告警、稳定性结论、检测状态等用同一套徽章口径。 */

export function alertBadge(alert: boolean | null | undefined) {
  if (alert === null || alert === undefined) {
    return <span className="badge badge-muted">暂无数据</span>
  }
  return alert
    ? <span className="badge badge-alert">漂移告警</span>
    : <span className="badge badge-stable">未告警</span>
}

export function stabilityBadge(conclusion: string | null | undefined) {
  if (!conclusion || conclusion === '暂无数据') {
    return <span className="badge badge-muted">暂无数据</span>
  }
  return conclusion === '稳定'
    ? <span className="badge badge-stable">稳定</span>
    : <span className="badge badge-alert">{conclusion}</span>
}

export function datasetStatusBadge(status: string) {
  const map: Record<string, string> = {
    待处理: 'badge-info',
    检测中: 'badge-warn',
    已完成: 'badge-stable',
    失败: 'badge-alert',
  }
  return <span className={`badge ${map[status] ?? 'badge-muted'}`}>{status}</span>
}

export function submitBadge(submitStatus: string) {
  return submitStatus === '已提交'
    ? <span className="badge badge-stable">已提交·唯一结果</span>
    : <span className="badge badge-muted">未提交</span>
}

export function currentBaselineBadge(isCurrent: boolean) {
  return isCurrent
    ? <span className="badge badge-info">当前基线</span>
    : <span className="badge badge-muted">候选基线</span>
}

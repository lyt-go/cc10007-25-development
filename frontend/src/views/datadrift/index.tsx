import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'
import { alertBadge, stabilityBadge } from '../revalidation/badges'

const ENDPOINT = '/api/datadrift'
const columns = [
  "检测编号",
  "监控数据集",
  "基线版本",
  "漂移度量",
  "漂移阈值",
  "检测频率",
  "告警接收人",
  "最近漂移值"
]
const actions = [
  "提交规则评审",
  "启用检测",
  "关闭检测"
]
const statuses = [
  "草稿",
  "规则评审中",
  "已启用",
  "已关闭"
]
const stats = [
  {
    "label": "漂移检测总数",
    "value": 0
  },
  {
    "label": "已启用检测",
    "value": 0
  },
  {
    "label": "评审中检测",
    "value": 0
  }
]

type Row = Record<string, string | number | boolean | null>

export default function DatadriftView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [selected, setSelected] = useState<Row | null>(null)
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('漂移检测列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '数据漂移列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      })
      if (!response.ok) {
        throw new Error('数据漂移动作未生效，请稍后重试')
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '数据漂移操作失败')
    }
  }

  async function openDetail(row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}`)
      if (!response.ok) {
        throw new Error('漂移检测详情读取失败')
      }
      setSelected(await response.json())
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '漂移检测详情读取失败')
    }
  }

  return (
    <section className="page" data-module="datadrift">
      <header className="page-head">
        <div>
          <h2>数据漂移管理</h2>
          <p className="page-desc">监控数据分布和特征漂移；待处理明细接收评分卡复验明细数据集，SCOR-0003 的告警与稳定性结论同步到本清单。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('漂移检测登记入口尚未接入审批流')}>
            登记漂移检测
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出数据漂移清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {stats.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>关联数据集</th>
            <th>复验接收状态</th>
            <th>漂移告警</th>
            <th>评分稳定性</th>
            <th>当前基线</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => (
                <td key={column}>
                  {column === '检测编号' ? (
                    <button className="link" type="button" onClick={() => void openDetail(row)}>{String(row[column] ?? '—')}</button>
                  ) : (
                    row[column] ?? '—'
                  )}
                </td>
              ))}
              <td>{String(row.关联数据集编号 ?? '—')}</td>
              <td>{row.复验接收状态
                ? (row.复验接收状态 === '检测中'
                  ? <span className="badge badge-warn">检测中·不可引用</span>
                  : <span className={row.复验接收状态 === '失败' ? 'badge badge-alert' : 'badge badge-stable'}>{String(row.复验接收状态)}</span>)
                : <span className="badge badge-muted">暂无数据</span>}</td>
              <td>{alertBadge(row.漂移告警 as boolean | null)}</td>
              <td>{stabilityBadge(row.评分稳定性 as string | null)}</td>
              <td>{row.当前基线版本 ? <span className="badge badge-info">{String(row.当前基线版本)}</span> : '—'}</td>
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 5}>暂无数据漂移数据，可先登记漂移检测</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条数据漂移记录；检测中的数据集不能作为评分卡当前依据</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>

      {selected && (
        <>
          <div className="drawer-mask" onClick={() => setSelected(null)} />
          <aside className="drawer" role="dialog" aria-label="漂移检测详情">
            <div className="drawer-head">
              <h3>{String(selected.检测编号)} · 数据漂移待处理明细</h3>
              <button className="btn small" type="button" onClick={() => setSelected(null)}>关闭</button>
            </div>
            <div className="detail-panel">
              <h3>检测配置</h3>
              <div className="kv-grid">
                <div className="kv-item"><span className="kv-label">监控数据集</span>{String(selected.监控数据集 ?? '—')}</div>
                <div className="kv-item"><span className="kv-label">基线版本</span>{String(selected.基线版本 ?? '—')}</div>
                <div className="kv-item"><span className="kv-label">漂移度量/阈值</span>{String(selected.漂移度量 ?? '—')} / {String(selected.漂移阈值 ?? '—')}</div>
                <div className="kv-item"><span className="kv-label">检测频率</span>{String(selected.检测频率 ?? '—')}</div>
                <div className="kv-item"><span className="kv-label">告警接收人</span>{String(selected.告警接收人 ?? '—')}</div>
                <div className="kv-item"><span className="kv-label">最近漂移值</span>{String(selected.最近漂移值 ?? '—')}</div>
              </div>
            </div>
            <div className="detail-panel">
              <h3>评分卡复验同步结论（SCOR-0003）</h3>
              <div className="kv-grid">
                <div className="kv-item"><span className="kv-label">关联数据集编号</span>{String(selected.关联数据集编号 ?? '—')}</div>
                <div className="kv-item"><span className="kv-label">关联评分卡</span>{String(selected.关联评分卡 ?? '—')}</div>
                <div className="kv-item"><span className="kv-label">当前基线版本</span>{String(selected.当前基线版本 ?? '—')}</div>
                <div className="kv-item"><span className="kv-label">复验接收状态</span>{String(selected.复验接收状态 ?? '暂无数据')}</div>
                <div className="kv-item"><span className="kv-label">漂移告警</span>{alertBadge(selected.漂移告警 as boolean | null)}</div>
                <div className="kv-item"><span className="kv-label">评分稳定性</span>{stabilityBadge(selected.评分稳定性 as string | null)}</div>
                <div className="kv-item"><span className="kv-label">复验批次号</span>{String(selected.复验批次号 ?? '—')}</div>
                <div className="kv-item"><span className="kv-label">提交状态</span>{String(selected.提交状态 ?? '—')}</div>
              </div>
              <p className="section-note">待处理明细：{String(selected.待处理明细 ?? '等待评分卡复验明细数据集')}</p>
            </div>
          </aside>
        </>
      )}
    </section>
  )
}

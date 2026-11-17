import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'
import { alertBadge, stabilityBadge } from '../revalidation/badges'

const ENDPOINT = '/api/scorecard'
const columns = [
  "评分编号",
  "评分对象",
  "特征变量组",
  "变量分箱",
  "WOE编码",
  "变量权重",
  "基准分数",
  "评分刻度"
]
const actions = [
  "提交评分校验",
  "启用评分",
  "废弃评分"
]
const statuses = [
  "草稿",
  "评分校验中",
  "已启用",
  "已废弃"
]
const stats = [
  {
    "label": "评分卡总数",
    "value": 0
  },
  {
    "label": "已启用评分",
    "value": 0
  },
  {
    "label": "校验中评分",
    "value": 0
  }
]

type FeatureShift = {
  特征: string
  特征PSI: number
  偏移阈值: number
  显著漂移阈值: number
  偏移等级: string
}

type Conclusion = {
  监控数据集: string
  数据集编号: string
  基线版本: string
  基线类型: string
  漂移告警: boolean
  稳定性结论: string
  评分PSI: number
  评分稳定阈值: number
  偏移特征: string
  特征偏移明细: FeatureShift[]
  批次号: string
}

type RevalidationDetail = Conclusion & {
  明细编号: string
  是否当前基线: boolean
}

type LinkedDataset = {
  数据集编号: string
  监控数据集: string
  状态: string
  当前基线版本: string
  提交状态: string
}

type Row = Record<string, string | number | boolean | null>
type DetailRow = Row & {
  复验空态说明?: string
  当前复验结论?: Conclusion
  关联监控数据集?: LinkedDataset[]
  复验明细数据集?: RevalidationDetail[]
}

export default function ScorecardView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [selected, setSelected] = useState<DetailRow | null>(null)
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('评分卡列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '评分卡列表读取失败')
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
        throw new Error('评分卡动作未生效，请稍后重试')
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '评分卡操作失败')
    }
  }

  async function openDetail(row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}`)
      if (!response.ok) {
        throw new Error('评分卡详情读取失败')
      }
      setSelected(await response.json())
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '评分卡详情读取失败')
    }
  }

  return (
    <section className="page" data-module="scorecard">
      <header className="page-head">
        <div>
          <h2>评分卡管理</h2>
          <p className="page-desc">管理用户或业务对象的评分卡模型，定义特征分箱、WOE编码和变量权重；详情读取同一监控数据集展示漂移告警、稳定性结论与特征偏移。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('评分卡登记入口尚未接入审批流')}>
            登记评分卡
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出评分卡清单
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
                  {column === '评分编号' ? (
                    <button className="link" type="button" onClick={() => void openDetail(row)}>{String(row[column] ?? '—')}</button>
                  ) : (
                    row[column] ?? '—'
                  )}
                </td>
              ))}
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
              <td className="empty-state" colSpan={columns.length + 4}>暂无评分卡数据，可先登记评分卡</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条评分卡记录；SCOR-0003 复验结论已同步到数据漂移清单</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>

      {selected && <ScorecardDrawer detail={selected} onClose={() => setSelected(null)} />}
    </section>
  )
}

function ScorecardDrawer({ detail, onClose }: { detail: DetailRow; onClose: () => void }) {
  const conclusion = detail.当前复验结论
  const linked = detail.关联监控数据集 ?? []
  const allDetails = detail.复验明细数据集 ?? []
  return (
    <>
      <div className="drawer-mask" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="评分卡复验详情">
        <div className="drawer-head">
          <h3>{String(detail.评分编号)} · {String(detail.评分对象)}</h3>
          <button className="btn small" type="button" onClick={onClose}>关闭</button>
        </div>

        <div className="detail-panel">
          <h3>评分卡基础信息</h3>
          <div className="kv-grid">
            <div className="kv-item"><span className="kv-label">状态</span>{String(detail.status ?? '—')}</div>
            <div className="kv-item"><span className="kv-label">特征变量组</span>{String(detail.特征变量组 ?? '—')}</div>
            <div className="kv-item"><span className="kv-label">基准分数</span>{String(detail.基准分数 ?? '—')}</div>
          </div>
        </div>

        <div className="detail-panel">
          <h3>数据漂移驱动的当前复验结论</h3>
          {conclusion ? (
            <>
              <div className="kv-grid">
                <div className="kv-item"><span className="kv-label">监控数据集</span>{conclusion.监控数据集}</div>
                <div className="kv-item"><span className="kv-label">当前基线</span>{conclusion.基线版本}（{conclusion.基线类型}）</div>
                <div className="kv-item"><span className="kv-label">处理批次号</span>{conclusion.批次号}</div>
                <div className="kv-item"><span className="kv-label">漂移告警</span>{alertBadge(conclusion.漂移告警)}</div>
                <div className="kv-item"><span className="kv-label">稳定性结论</span>{stabilityBadge(conclusion.稳定性结论)}</div>
                <div className="kv-item"><span className="kv-label">评分PSI / 阈值</span>{conclusion.评分PSI} / {conclusion.评分稳定阈值}</div>
              </div>
              <p className="section-note">偏移特征：{conclusion.偏移特征 || '无（各特征 PSI 均在阈值内）'}</p>
              <table className="nested-table">
                <thead>
                  <tr><th>特征</th><th>特征PSI</th><th>偏移阈值</th><th>显著漂移阈值</th><th>偏移等级</th></tr>
                </thead>
                <tbody>
                  {conclusion.特征偏移明细.map((f) => (
                    <tr key={f.特征}>
                      <td>{f.特征}</td>
                      <td>{f.特征PSI}</td>
                      <td>{f.偏移阈值}</td>
                      <td>{f.显著漂移阈值}</td>
                      <td>{f.偏移等级 === '稳定'
                        ? <span className="badge badge-stable">稳定</span>
                        : <span className={f.偏移等级 === '显著漂移' ? 'badge badge-alert' : 'badge badge-warn'}>{f.偏移等级}</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            // 核验码 2570c9b2：评分卡空态与暂无数据需说明
            <p className="section-note">{detail.复验空态说明 ?? '暂无数据：该评分卡暂无数据漂移驱动的复验明细'}</p>
          )}
        </div>

        <div className="detail-panel">
          <h3>关联监控数据集（同一监控数据集可含多基线判断）</h3>
          {linked.length === 0 ? (
            <p className="section-note">暂无数据：尚未接收到供新能力链路推送的监控数据集</p>
          ) : (
            <table className="nested-table">
              <thead>
                <tr><th>数据集编号</th><th>监控数据集</th><th>接收状态</th><th>当前基线</th><th>提交状态</th></tr>
              </thead>
              <tbody>
                {linked.map((d) => (
                  <tr key={d.数据集编号}>
                    <td>{d.数据集编号}</td>
                    <td>{d.监控数据集}</td>
                    <td>{d.状态 === '检测中'
                      ? <span className="badge badge-warn">检测中·不可引用</span>
                      : <span className={d.状态 === '失败' ? 'badge badge-alert' : 'badge badge-stable'}>{d.状态}</span>}</td>
                    <td>{d.当前基线版本 || '—'}</td>
                    <td>{d.提交状态}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {allDetails.length > 1 && (
          <div className="detail-panel">
            <h3>全部基线复验判断（评分卡仅引用一个当前基线）</h3>
            <table className="nested-table">
              <thead>
                <tr><th>数据集</th><th>基线版本</th><th>基线类型</th><th>评分PSI</th><th>漂移告警</th><th>稳定性</th></tr>
              </thead>
              <tbody>
                {allDetails.map((d) => (
                  <tr key={d.明细编号 ?? d.基线版本}>
                    <td>{d.数据集编号}</td>
                    <td>{d.基线版本}{d.是否当前基线 ? '（当前）' : ''}</td>
                    <td>{d.基线类型}</td>
                    <td>{d.评分PSI}</td>
                    <td>{alertBadge(d.漂移告警)}</td>
                    <td>{stabilityBadge(d.稳定性结论)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </aside>
    </>
  )
}

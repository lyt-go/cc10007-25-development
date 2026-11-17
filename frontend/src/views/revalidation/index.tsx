import { useCallback, useEffect, useState } from 'react'

import { request } from '@/api/client'
import {
  alertBadge,
  currentBaselineBadge,
  datasetStatusBadge,
  stabilityBadge,
  submitBadge,
} from './badges'

const ENDPOINT = '/api/revalidation'

type FeatureShift = {
  特征: string
  特征PSI: number
  偏移阈值: number
  显著漂移阈值: number
  是否偏移: boolean
  偏移等级: string
}

type Detail = {
  id: number
  明细编号: string
  批次号: string
  数据集编号: string
  监控数据集: string
  评分编号: string
  基线版本: string
  基线类型: string
  是否当前基线: boolean
  特征偏移明细: FeatureShift[]
  偏移特征数: number
  偏移特征: string
  评分PSI: number
  评分稳定阈值: number
  漂移告警: boolean
  告警说明: string
  稳定性结论: string
  复验时间: string
}

type Baseline = {
  id: number
  数据集编号: string
  基线版本: string
  基线类型: string
  状态: string
  观察窗口说明: string
}

type Batch = {
  id: number
  批次号: string
  数据集编号: string
  处理时间: string
  基线版本数: number
  明细条数: number
  状态: string
}

type CurrentBaseline = {
  数据集编号: string
  可用: boolean
  message: string
  当前基线版本?: string
  基线类型?: string
  候选基线数?: number
}

type Dataset = {
  id: number
  数据集编号: string
  监控数据集: string
  接收时间: string
  来源链路: string
  观察窗口: string
  评分编号: string
  状态: string
  重试次数: number
  异常说明: string
  提交状态: string
  当前基线版本: string
  基线版本?: Baseline[]
  处理批次?: Batch[]
  复验明细?: Detail[]
  当前基线?: CurrentBaseline
}

type Row = Record<string, string | number | null>

/** 数据漂移待处理明细：接收评分卡复验明细数据集，并驱动阈值复验与批次归档。 */
export default function RevalidationView() {
  const [rows, setRows] = useState<Dataset[]>([])
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState('')
  const [keyword, setKeyword] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [selected, setSelected] = useState<Dataset | null>(null)
  const [contract, setContract] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(false)

  const reload = useCallback(async () => {
    setErrorMessage('')
    const params = new URLSearchParams()
    if (statusFilter) params.set('status', statusFilter)
    if (keyword) params.set('keyword', keyword)
    try {
      const response = await request(`${ENDPOINT}/datasets?${params.toString()}`)
      if (!response.ok) throw new Error('监控数据集列表读取失败')
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '监控数据集列表读取失败')
    }
  }, [statusFilter, keyword])

  useEffect(() => {
    void reload()
  }, [reload])

  // 核验码 251069f7：完成后刷新视图（核验码 259c2359）——动作成功后重新拉取列表与详情
  const refreshAfterAction = useCallback(async (message: string, selectedId?: number) => {
    setNotice(message)
    await reload()
    if (selectedId) {
      await openDetail(selectedId, true)
    }
  }, [reload])

  async function postAction(path: string, okMessage: string, selectedId?: number) {
    setLoading(true)
    setErrorMessage('')
    try {
      const response = await request(path, { method: 'POST', body: JSON.stringify({}) })
      const payload = await response.json().catch(() => null)
      const message = payload?.message ?? (response.ok ? okMessage : '操作未生效，请稍后重试')
      if (!response.ok || payload?.ok === false) {
        setErrorMessage(message)
      } else {
        await refreshAfterAction(message, selectedId)
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '请求未送达，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  async function openDetail(id: number, silent = false) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/datasets/${id}`)
      if (!response.ok) throw new Error('监控数据集明细读取失败')
      setSelected(await response.json())
    } catch (error) {
      if (!silent) setErrorMessage(error instanceof Error ? error.message : '监控数据集明细读取失败')
    }
  }

  async function openContract() {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/contract/scor-0003`)
      if (!response.ok) throw new Error('SCOR-0003 契约验证读取失败')
      setContract(await response.json())
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'SCOR-0003 契约验证读取失败')
    }
  }

  const stats = [
    { label: '监控数据集', value: total },
    { label: '待处理', value: rows.filter((r) => r.状态 === '待处理').length },
    { label: '检测中（不可引用）', value: rows.filter((r) => r.状态 === '检测中').length },
    { label: '失败待重试', value: rows.filter((r) => r.状态 === '失败').length },
    { label: '已提交唯一结果', value: rows.filter((r) => r.提交状态 === '已提交').length },
  ]

  return (
    <section className="page" data-module="revalidation">
      <header className="page-head">
        <div>
          <h2>评分卡复验（数据漂移驱动）</h2>
          <p className="page-desc">
            接收供新能力链路的漂移检测监控数据集与评分卡特征记录，按阈值计算特征偏移与评分稳定性，
            生成评分卡复验明细数据集并按处理批次归档（核验码 258e94b9）。
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" type="button" onClick={() => void openContract()}>
            SCOR-0003 契约验证样本
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

      <form
        className="filter-bar"
        onSubmit={(event) => { event.preventDefault(); void reload() }}
      >
        <label className="filter-item">
          <span>数据集关键字</span>
          <input
            value={keyword}
            placeholder="按数据集编号或名称检索"
            onChange={(event) => setKeyword(event.target.value)}
          />
        </label>
        <label className="filter-item">
          <span>接收状态</span>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">全部</option>
            <option value="待处理">待处理</option>
            <option value="检测中">检测中</option>
            <option value="已完成">已完成</option>
            <option value="失败">失败</option>
          </select>
        </label>
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => { setStatusFilter(''); setKeyword('') }}>
          重置条件
        </button>
      </form>

      {notice && <p className="section-note ok-text">最近操作：{notice}</p>}

      <table className="data-table">
        <thead>
          <tr>
            <th>数据集编号</th>
            <th>监控数据集</th>
            <th>评分编号</th>
            <th>接收状态</th>
            <th>当前基线</th>
            <th>重试</th>
            <th>提交状态</th>
            <th>异常说明</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              <td>
                <button className="link" type="button" onClick={() => void openDetail(Number(row.id))}>
                  {row.数据集编号}
                </button>
              </td>
              <td>{row.监控数据集}</td>
              <td>{row.评分编号}</td>
              <td>{datasetStatusBadge(row.状态)}</td>
              <td>{row.当前基线版本 ? <span className="badge badge-info">{row.当前基线版本}</span> : '—'}</td>
              <td>{row.重试次数}</td>
              <td>{submitBadge(row.提交状态)}</td>
              <td>{row.异常说明 || '—'}</td>
              <td className="row-actions">
                <button
                  className="btn small"
                  type="button"
                  disabled={loading || row.状态 === '检测中' || row.状态 === '失败'}
                  title={row.状态 === '失败' ? '失败数据集需先重试修正' : row.状态 === '检测中' ? '检测中数据集不可引用' : '按新链路计算评分稳定性'}
                  onClick={() => void postAction(`${ENDPOINT}/datasets/${row.id}/revalidate`, '复验完成', Number(row.id))}
                >
                  执行复验
                </button>
                <button
                  className="btn small"
                  type="button"
                  disabled={loading || row.状态 !== '失败'}
                  title="失败重试：修正特征记录后重新接收"
                  onClick={() => void postAction(`${ENDPOINT}/datasets/${row.id}/retry`, '重试完成', Number(row.id))}
                >
                  失败重试
                </button>
                <button
                  className="btn small primary"
                  type="button"
                  disabled={loading || row.状态 !== '已完成' || row.提交状态 === '已提交'}
                  title="只接收含评分卡复验明细数据集的唯一可用结果"
                  onClick={() => void postAction(`${ENDPOINT}/datasets/${row.id}/submit`, '提交完成', Number(row.id))}
                >
                  提交唯一结果
                </button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={9}>
                暂无监控数据集：供新能力链路尚未推送漂移检测监控数据，数据漂移待处理明细为空
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 个监控数据集；评分卡不能引用仍在检测中的数据集作为当前依据</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>

      {selected && (
        <DetailDrawer
          dataset={selected}
          onClose={() => setSelected(null)}
          onAction={(path, message) => void postAction(path, message, Number(selected.id))}
          loading={loading}
        />
      )}

      {contract && <ContractDrawer contract={contract} onClose={() => setContract(null)} />}
    </section>
  )
}

function DetailDrawer({
  dataset,
  onClose,
  onAction,
  loading,
}: {
  dataset: Dataset
  onClose: () => void
  onAction: (path: string, message: string) => void
  loading: boolean
}) {
  const details = dataset.复验明细 ?? []
  const baselines = dataset.基线版本 ?? []
  const batches = dataset.处理批次 ?? []
  const current = dataset.当前基线
  return (
    <>
      <div className="drawer-mask" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="监控数据集复验明细">
        <div className="drawer-head">
          <h3>{dataset.数据集编号} · {dataset.监控数据集}</h3>
          <button className="btn small" type="button" onClick={onClose}>关闭</button>
        </div>

        <div className="detail-panel">
          <h3>接收信息（新链路）</h3>
          <div className="kv-grid">
            <div className="kv-item"><span className="kv-label">来源链路</span>{dataset.来源链路}</div>
            <div className="kv-item"><span className="kv-label">接收时间</span>{dataset.接收时间}</div>
            <div className="kv-item"><span className="kv-label">观察窗口</span>{dataset.观察窗口}</div>
            <div className="kv-item"><span className="kv-label">评分编号</span>{dataset.评分编号}</div>
            <div className="kv-item"><span className="kv-label">接收状态</span>{datasetStatusBadge(dataset.状态)}</div>
            <div className="kv-item"><span className="kv-label">重试次数</span>{dataset.重试次数}</div>
          </div>
          {dataset.异常说明 && <p className="section-note error-text">异常说明：{dataset.异常说明}</p>}
        </div>

        <div className="detail-panel">
          <h3>当前基线选择</h3>
          {current?.可用 ? (
            <div className="kv-grid">
              <div className="kv-item"><span className="kv-label">当前基线版本</span>{current.当前基线版本}</div>
              <div className="kv-item"><span className="kv-label">基线类型</span>{current.基线类型}</div>
              <div className="kv-item"><span className="kv-label">候选可用基线数</span>{current.候选基线数}</div>
            </div>
          ) : (
            <p className="section-note error-text">{current?.message ?? '暂无可用当前基线'}</p>
          )}
          <p className="section-note">同一监控数据集存在两个可用基线时按“固定观察窗口优先、最近完整批次其次”确定唯一当前基线。</p>
          <table className="nested-table">
            <thead>
              <tr><th>基线版本</th><th>基线类型</th><th>基线状态</th><th>窗口说明</th></tr>
            </thead>
            <tbody>
              {baselines.map((b) => (
                <tr key={b.id}>
                  <td>{b.基线版本}</td>
                  <td>{b.基线类型}</td>
                  <td>{b.状态 === '检测中'
                    ? <span className="badge badge-warn">检测中·不可引用</span>
                    : <span className="badge badge-stable">{b.状态}</span>}</td>
                  <td>{b.观察窗口说明}</td>
                </tr>
              ))}
              {baselines.length === 0 && (
                <tr><td className="empty-state" colSpan={4}>暂无基线数据</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="detail-panel">
          <h3>评分卡复验明细数据集（阈值驱动）</h3>
          {details.length === 0 ? (
            <p className="section-note">
              暂无数据：{dataset.状态 === '检测中'
                ? '监控数据集仍在检测中，检测完成前不生成复验明细，评分卡不得引用'
                : dataset.状态 === '失败'
                  ? '接收校验失败，未形成复验明细，请先失败重试'
                  : '尚未执行复验，执行后将首次生成复验明细并按处理批次归档'}
            </p>
          ) : (
            details.map((d) => (
              <div key={d.id} className="detail-panel" style={{ background: '#fbfcfe' }}>
                <div className="drawer-head">
                  <h3>{d.基线版本} {currentBaselineBadge(d.是否当前基线)}</h3>
                  <span>{d.基线类型}</span>
                </div>
                <div className="kv-grid">
                  <div className="kv-item"><span className="kv-label">漂移告警</span>{alertBadge(d.漂移告警)}</div>
                  <div className="kv-item"><span className="kv-label">稳定性结论</span>{stabilityBadge(d.稳定性结论)}</div>
                  <div className="kv-item"><span className="kv-label">评分PSI / 阈值</span>{d.评分PSI} / {d.评分稳定阈值}</div>
                  <div className="kv-item"><span className="kv-label">偏移特征数</span>{d.偏移特征数}</div>
                  <div className="kv-item"><span className="kv-label">偏移特征</span>{d.偏移特征 || '—'}</div>
                  <div className="kv-item"><span className="kv-label">处理批次号</span>{d.批次号}</div>
                </div>
                <p className="section-note">{d.告警说明}</p>
                <table className="nested-table">
                  <thead>
                    <tr><th>特征</th><th>特征PSI</th><th>偏移阈值</th><th>显著漂移阈值</th><th>偏移等级</th></tr>
                  </thead>
                  <tbody>
                    {d.特征偏移明细.map((f) => (
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
              </div>
            ))
          )}
        </div>

        <div className="detail-panel">
          <h3>处理批次归档（可从数据批次追溯）</h3>
          <table className="nested-table">
            <thead>
              <tr><th>批次号</th><th>处理时间</th><th>基线版本数</th><th>明细条数</th><th>批次状态</th></tr>
            </thead>
            <tbody>
              {batches.map((b) => (
                <tr key={b.id}>
                  <td>{b.批次号}</td>
                  <td>{b.处理时间}</td>
                  <td>{b.基线版本数}</td>
                  <td>{b.明细条数}</td>
                  <td>{b.状态}</td>
                </tr>
              ))}
              {batches.length === 0 && (
                <tr><td className="empty-state" colSpan={5}>暂无处理批次，复验完成后自动归档</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="row-actions">
          <button
            className="btn"
            type="button"
            disabled={loading || dataset.状态 === '检测中' || dataset.状态 === '失败'}
            onClick={() => onAction(`${ENDPOINT}/datasets/${dataset.id}/revalidate`, '复验完成并已刷新视图')}
          >
            重新执行复验
          </button>
          <button
            className="btn"
            type="button"
            disabled={loading || dataset.状态 !== '失败'}
            onClick={() => onAction(`${ENDPOINT}/datasets/${dataset.id}/retry`, '失败重试完成并已刷新视图')}
          >
            失败重试
          </button>
          <button
            className="btn primary"
            type="button"
            disabled={loading || dataset.状态 !== '已完成' || dataset.提交状态 === '已提交'}
            onClick={() => onAction(`${ENDPOINT}/datasets/${dataset.id}/submit`, '唯一可用结果已提交')}
          >
            提交唯一结果
          </button>
        </div>
      </aside>
    </>
  )
}

function ContractDrawer({
  contract,
  onClose,
}: {
  contract: Record<string, unknown>
  onClose: () => void
}) {
  const checks = (contract.核验项 ?? []) as { 核验项: string; 通过: boolean; 说明: string }[]
  const current = contract.当前基线复验 as Detail | undefined
  return (
    <>
      <div className="drawer-mask" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="SCOR-0003 契约验证">
        <div className="drawer-head">
          <h3>SCOR-0003 契约验证样本（{String(contract.核验码)}）</h3>
          <button className="btn small" type="button" onClick={onClose}>关闭</button>
        </div>
        <div className="detail-panel">
          <p className="section-note">
            验证时核对：阈值、基线版本、特征偏移和评分稳定性；评分卡不能引用仍在检测中的数据集作为当前依据。
          </p>
          <table className="nested-table">
            <thead>
              <tr><th>核验项</th><th>结果</th><th>说明</th></tr>
            </thead>
            <tbody>
              {checks.map((c) => (
                <tr key={c.核验项}>
                  <td>{c.核验项}</td>
                  <td>{c.通过 ? <span className="badge badge-stable">通过</span> : <span className="badge badge-alert">不通过</span>}</td>
                  <td>{c.说明}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {current && (
          <div className="detail-panel">
            <h3>当前基线复验快照</h3>
            <div className="kv-grid">
              <div className="kv-item"><span className="kv-label">基线版本</span>{current.基线版本}</div>
              <div className="kv-item"><span className="kv-label">稳定性结论</span>{stabilityBadge(current.稳定性结论)}</div>
              <div className="kv-item"><span className="kv-label">漂移告警</span>{alertBadge(current.漂移告警)}</div>
              <div className="kv-item"><span className="kv-label">评分PSI</span>{current.评分PSI}</div>
              <div className="kv-item"><span className="kv-label">偏移特征</span>{current.偏移特征 || '—'}</div>
              <div className="kv-item"><span className="kv-label">批次号</span>{current.批次号}</div>
            </div>
          </div>
        )}
      </aside>
    </>
  )
}

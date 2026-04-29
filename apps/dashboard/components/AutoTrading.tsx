'use client'
import { useState, useEffect } from 'react'
import { API_BASE } from '@/lib/config'

export default function AutoTrading() {
  const [status, setStatus] = useState<any>(null)
  const [performance, setPerformance] = useState<any>(null)

  const fetchData = async () => {
    try {
      const [statusRes, perfRes] = await Promise.all([
        fetch(`${API_BASE}/api/trading/status`),
        fetch(`${API_BASE}/api/trading/performance`)
      ])
      setStatus(await statusRes.json())
      setPerformance(await perfRes.json())
    } catch (e) {}
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 5000)
    return () => clearInterval(interval)
  }, [])

  const handleStart = async () => {
    await fetch(`${API_BASE}/api/trading/start`, { method: 'POST' })
    fetchData()
  }

  const handleStop = async () => {
    await fetch(`${API_BASE}/api/trading/stop`, { method: 'POST' })
    fetchData()
  }

  return (
    <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-xl font-bold text-white">自主交易系统</h2>
        <div className="flex gap-2">
          <button onClick={handleStart} disabled={status?.running} className="px-4 py-2 bg-green-600 text-white rounded disabled:opacity-50">启动</button>
          <button onClick={handleStop} disabled={!status?.running} className="px-4 py-2 bg-red-600 text-white rounded disabled:opacity-50">停止</button>
        </div>
      </div>

      {status && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="bg-gray-800 p-4 rounded">
            <div className="text-gray-400 text-sm">账户余额</div>
            <div className="text-2xl font-bold text-white">${status.total_value?.toFixed(2)}</div>
          </div>
          <div className="bg-gray-800 p-4 rounded">
            <div className="text-gray-400 text-sm">PnL</div>
            <div className={`text-2xl font-bold ${status.pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
              {status.pnl >= 0 ? '+' : ''}{status.pnl?.toFixed(2)} ({status.pnl_pct?.toFixed(2)}%)
            </div>
          </div>
          <div className="bg-gray-800 p-4 rounded">
            <div className="text-gray-400 text-sm">持仓</div>
            <div className="text-2xl font-bold text-white">{status.position?.toFixed(4)} BTC</div>
          </div>
          <div className="bg-gray-800 p-4 rounded">
            <div className="text-gray-400 text-sm">状态</div>
            <div className={`text-2xl font-bold ${status.running ? 'text-green-500' : 'text-gray-500'}`}>
              {status.running ? '运行中' : '已停止'}
            </div>
          </div>
        </div>
      )}

      {performance && (
        <div className="bg-gray-800 p-4 rounded">
          <h3 className="text-white font-bold mb-3">交易历史</h3>
          <div className="text-gray-400 text-sm mb-2">
            总交易: {performance.total_trades} | 胜率: {(performance.win_rate * 100).toFixed(1)}%
          </div>
          <div className="space-y-2 max-h-60 overflow-y-auto">
            {performance.trades?.map((trade: any, i: number) => (
              <div key={i} className="text-sm text-gray-300 border-b border-gray-700 pb-2">
                <span className="text-gray-500">{trade.time?.slice(11, 19)}</span> |
                <span className={trade.type?.includes('open') ? 'text-green-400' : 'text-red-400'}> {trade.type}</span> |
                ${trade.price?.toFixed(2)}
                {trade.pnl && <span className={trade.pnl >= 0 ? 'text-green-500' : 'text-red-500'}> | PnL: ${trade.pnl.toFixed(2)}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

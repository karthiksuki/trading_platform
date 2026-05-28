import { useEffect, useMemo, useState } from 'react'

type AdminPageProps = {
  adminEmail: string
  adminPassword: string
  onExit: () => void
}

type Market = {
  id: number
  symbol: string
  name: string
  status: 'OPEN' | 'PAUSED' | 'CLOSED'
  tick_size: number
  min_order_size: number
}

type LogItem = {
  id: number
  action: string
  user_id: string
  market_id: number | null
  details: string
  created_at: string
}

function AdminPage({ adminEmail, adminPassword, onExit }: AdminPageProps) {
  const [isBusy, setIsBusy] = useState(false)
  const [status, setStatus] = useState('Admin monitoring online.')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [refreshSeconds, setRefreshSeconds] = useState(5)
  const [summary, setSummary] = useState<Record<string, number>>({})
  const [markets, setMarkets] = useState<Market[]>([])
  const [marketHealth, setMarketHealth] = useState<Array<Record<string, unknown>>>([])
  const [logs, setLogs] = useState<LogItem[]>([])
  const [logActionFilter, setLogActionFilter] = useState('')
  const [logMarketFilter, setLogMarketFilter] = useState('')
  const [newMarketSymbol, setNewMarketSymbol] = useState('BTCUSD')
  const [newMarketName, setNewMarketName] = useState('Bitcoin / USD')
  const [tickSize, setTickSize] = useState(0.01)
  const [minOrderSize, setMinOrderSize] = useState(0.001)
  const [cleanupMinutes, setCleanupMinutes] = useState(60)
  const [lastReconcileMismatches, setLastReconcileMismatches] = useState(0)
  const [riskTopUsers, setRiskTopUsers] = useState<Array<{ user_id: string; exposure: number }>>([])

  const authQuery = useMemo(
    () =>
      `admin_email=${encodeURIComponent(adminEmail)}&admin_password=${encodeURIComponent(adminPassword)}`,
    [adminEmail, adminPassword],
  )

  const callApi = async <T,>(url: string, options?: RequestInit): Promise<T> => {
    const response = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...(options?.headers ?? {}) },
      ...options,
    })
    if (!response.ok) {
      const message = await response.text()
      throw new Error(message || `Request failed: ${response.status}`)
    }
    return (await response.json()) as T
  }

  const loadMonitoring = async () => {
    const [summaryResponse, marketsResponse, healthResponse, logsResponse] = await Promise.all([
      callApi<Record<string, number>>(`/api/admin/monitoring/summary?${authQuery}`),
      callApi<Market[]>(`/api/admin/markets?${authQuery}`),
      callApi<Array<Record<string, unknown>>>(`/api/admin/monitoring/market-health?${authQuery}`),
      callApi<LogItem[]>(
        `/api/admin/monitoring/logs?${authQuery}&limit=80${
          logActionFilter ? `&action=${encodeURIComponent(logActionFilter)}` : ''
        }${logMarketFilter ? `&market_id=${encodeURIComponent(logMarketFilter)}` : ''}`,
      ),
    ])
    setSummary(summaryResponse)
    setMarkets(marketsResponse)
    setMarketHealth(healthResponse)
    setLogs(logsResponse)
  }

  const refreshNow = async () => {
    try {
      setIsBusy(true)
      await loadMonitoring()
      setStatus(`Monitoring refreshed at ${new Date().toLocaleTimeString()}.`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Monitoring refresh failed.')
    } finally {
      setIsBusy(false)
    }
  }

  useEffect(() => {
    void refreshNow()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!autoRefresh) return
    const interval = window.setInterval(() => {
      void loadMonitoring().catch(() => {
        // keep polling resilient without surfacing noisy transient errors
      })
    }, Math.max(refreshSeconds, 3) * 1000)
    return () => window.clearInterval(interval)
  }, [autoRefresh, refreshSeconds, authQuery, logActionFilter, logMarketFilter])

  const createMarket = async () => {
    try {
      setIsBusy(true)
      await callApi('/api/admin/markets', {
        method: 'POST',
        body: JSON.stringify({
          admin_email: adminEmail,
          admin_password: adminPassword,
          symbol: newMarketSymbol,
          name: newMarketName,
          tick_size: tickSize,
          min_order_size: minOrderSize,
        }),
      })
      setStatus(`Market ${newMarketSymbol.toUpperCase()} created.`)
      await refreshNow()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Create market failed.')
    } finally {
      setIsBusy(false)
    }
  }

  const updateMarketStatus = async (marketId: number, nextStatus: 'OPEN' | 'PAUSED' | 'CLOSED') => {
    try {
      setIsBusy(true)
      await callApi(`/api/admin/markets/${marketId}/status`, {
        method: 'POST',
        body: JSON.stringify({
          admin_email: adminEmail,
          admin_password: adminPassword,
          status: nextStatus,
        }),
      })
      setStatus(`Market ${marketId} status -> ${nextStatus}.`)
      await refreshNow()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Market status update failed.')
    } finally {
      setIsBusy(false)
    }
  }

  const runStaleCleanup = async () => {
    try {
      setIsBusy(true)
      const result = await callApi<{ cancelled_orders: number }>('/api/admin/ops/stale-order-cleanup', {
        method: 'POST',
        body: JSON.stringify({
          admin_email: adminEmail,
          admin_password: adminPassword,
          max_age_minutes: cleanupMinutes,
        }),
      })
      setStatus(`Stale cleanup completed. Cancelled orders: ${result.cancelled_orders}.`)
      await refreshNow()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Stale cleanup failed.')
    } finally {
      setIsBusy(false)
    }
  }

  const runReconcile = async () => {
    try {
      setIsBusy(true)
      const result = await callApi<{ mismatches: unknown[] }>('/api/admin/ops/reconcile', {
        method: 'POST',
        body: JSON.stringify({
          admin_email: adminEmail,
          admin_password: adminPassword,
        }),
      })
      setLastReconcileMismatches(result.mismatches.length)
      setStatus(`Reconciliation completed. Mismatches: ${result.mismatches.length}.`)
      await refreshNow()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Reconciliation failed.')
    } finally {
      setIsBusy(false)
    }
  }

  const runRiskRecalc = async () => {
    try {
      setIsBusy(true)
      const result = await callApi<{ top_exposures: Array<{ user_id: string; exposure: number }> }>(
        '/api/admin/ops/risk-recalc',
        {
          method: 'POST',
          body: JSON.stringify({
            admin_email: adminEmail,
            admin_password: adminPassword,
            limit: 10,
          }),
        },
      )
      setRiskTopUsers(result.top_exposures)
      setStatus('Risk recalculation completed.')
      await refreshNow()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Risk recalculation failed.')
    } finally {
      setIsBusy(false)
    }
  }

  return (
    <main className="auth-card dashboard">
      <div className="topbar">
        <div>
          <h1>Admin Console</h1>
          <p className="subtitle">Monitoring, market controls, and operational tooling</p>
        </div>
        <button className="ghost-btn" onClick={onExit}>
          Exit Admin
        </button>
      </div>

      <p className="wallet">
        Admin session: <code>{adminEmail}</code>
      </p>
      <p className="status">{status}</p>

      <section className="panel-grid">
        <div className="panel">
          <h3>Monitoring Controls</h3>
          <label>
            Auto Refresh
            <select value={autoRefresh ? 'on' : 'off'} onChange={(e) => setAutoRefresh(e.target.value === 'on')}>
              <option value="on">On</option>
              <option value="off">Off</option>
            </select>
          </label>
          <label>
            Refresh Interval (seconds)
            <input
              type="number"
              value={refreshSeconds}
              min={3}
              onChange={(e) => setRefreshSeconds(Number(e.target.value))}
              disabled={!autoRefresh}
            />
          </label>
          <div className="actions">
            <button disabled={isBusy} onClick={() => void refreshNow()}>
              Refresh Now
            </button>
          </div>
        </div>

        <div className="panel">
          <h3>Summary</h3>
          <ul className="list">
            <li>Open Orders: {summary.open_orders ?? 0}</li>
            <li>Trades (1h): {summary.trades_1h ?? 0}</li>
            <li>Trades (24h): {summary.trades_24h ?? 0}</li>
            <li>Markets Open: {summary.markets_open ?? 0}</li>
            <li>Total Markets: {summary.markets_total ?? 0}</li>
            <li>Frozen Users: {summary.frozen_users ?? 0}</li>
            <li>Recent Failures: {summary.recent_failures ?? 0}</li>
            <li>Last Reconcile Mismatches: {lastReconcileMismatches}</li>
          </ul>
        </div>

        <div className="panel">
          <h3>Create Market</h3>
          <label>
            Symbol
            <input value={newMarketSymbol} onChange={(e) => setNewMarketSymbol(e.target.value.toUpperCase())} />
          </label>
          <label>
            Name
            <input value={newMarketName} onChange={(e) => setNewMarketName(e.target.value)} />
          </label>
          <label>
            Tick Size
            <input type="number" value={tickSize} onChange={(e) => setTickSize(Number(e.target.value))} />
          </label>
          <label>
            Min Order Size
            <input type="number" value={minOrderSize} onChange={(e) => setMinOrderSize(Number(e.target.value))} />
          </label>
          <div className="actions">
            <button disabled={isBusy} onClick={() => void createMarket()}>
              Create Market
            </button>
          </div>
        </div>

        <div className="panel">
          <h3>Operations</h3>
          <label>
            Stale Cleanup Minutes
            <input type="number" value={cleanupMinutes} onChange={(e) => setCleanupMinutes(Number(e.target.value))} />
          </label>
          <div className="actions">
            <button disabled={isBusy} onClick={() => void runStaleCleanup()}>
              Cleanup Stale Orders
            </button>
            <button disabled={isBusy} onClick={() => void runReconcile()}>
              Run Reconciliation
            </button>
            <button disabled={isBusy} onClick={() => void runRiskRecalc()}>
              Recalculate Risk
            </button>
          </div>
        </div>

        <div className="panel">
          <h3>Market Controls</h3>
          <ul className="list">
            {markets.map((market) => (
              <li key={market.id}>
                {market.symbol} ({market.name}) status={market.status}
                <div className="actions">
                  <button disabled={isBusy} onClick={() => void updateMarketStatus(market.id, 'OPEN')}>
                    Open
                  </button>
                  <button disabled={isBusy} onClick={() => void updateMarketStatus(market.id, 'PAUSED')}>
                    Pause
                  </button>
                  <button disabled={isBusy} onClick={() => void updateMarketStatus(market.id, 'CLOSED')}>
                    Close
                  </button>
                </div>
              </li>
            ))}
            {!markets.length && <li>No markets yet</li>}
          </ul>
        </div>

        <div className="panel">
          <h3>Market Health</h3>
          <ul className="list">
            {marketHealth.map((item) => (
              <li key={String(item.market_id)}>
                {String(item.symbol)} bid={String(item.best_bid ?? '-')} ask={String(item.best_ask ?? '-')} spread=
                {String(item.spread ?? '-')}
              </li>
            ))}
            {!marketHealth.length && <li>No market health data</li>}
          </ul>
        </div>

        <div className="panel">
          <h3>Audit Logs</h3>
          <label>
            Action Filter
            <input value={logActionFilter} onChange={(e) => setLogActionFilter(e.target.value)} placeholder="ADMIN_MARKET_CREATE" />
          </label>
          <label>
            Market ID Filter
            <input value={logMarketFilter} onChange={(e) => setLogMarketFilter(e.target.value)} placeholder="1" />
          </label>
          <div className="actions">
            <button disabled={isBusy} onClick={() => void refreshNow()}>
              Apply Filters
            </button>
          </div>
          <ul className="list">
            {logs.map((log) => (
              <li key={log.id}>
                [{log.action}] {log.details}
              </li>
            ))}
            {!logs.length && <li>No logs found</li>}
          </ul>
        </div>

        <div className="panel">
          <h3>Top Risk Exposure</h3>
          <ul className="list">
            {riskTopUsers.map((row) => (
              <li key={row.user_id}>
                {row.user_id}: {row.exposure.toFixed(2)}
              </li>
            ))}
            {!riskTopUsers.length && <li>Run risk recalculation to view exposure</li>}
          </ul>
        </div>
      </section>
    </main>
  )
}

export default AdminPage

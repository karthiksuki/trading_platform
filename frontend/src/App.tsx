import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import './App.css'
import AdminPage from './AdminPage'

const ADMIN_SESSION_STORAGE_KEY = 'trading_platform_admin_session'
const ACCOUNT_STORAGE_KEY = 'trading_platform_account'

type Outcome = 'YES' | 'NO'
type OrderSide = 'BUY' | 'SELL'

type OrderLevel = {
  price: number
  quantity: number
}

type OutcomeBook = {
  bids: OrderLevel[]
  asks: OrderLevel[]
  best_bid: number | null
  best_ask: number | null
}

type PredictionMarket = {
  id: number
  market_id: number
  symbol: string
  name: string
  question: string
  description: string
  status: string
  tick_size: number
  min_order_size: number
  outcomes: Record<Outcome, OutcomeBook>
  last_trade_price: number | null
  last_trade_outcome: Outcome | null
  source?: string
  liquidity?: number
  volume?: number
}

type TradingAccount = {
  user_id: string
  email?: string
  user_name: string
  user_profile: string
  solana_wallet_address?: string | null
}

type AppView = 'landing' | 'signup' | 'dashboard' | 'admin-login'

const emptyBook: OutcomeBook = {
  bids: [],
  asks: [],
  best_bid: null,
  best_ask: null,
}

function App() {
  const [status, setStatus] = useState('Browse live prediction markets. Sign up when you are ready to trade.')
  const [isBusy, setIsBusy] = useState(false)
  const [appMode, setAppMode] = useState<'trader' | 'admin'>('trader')
  const [view, setView] = useState<AppView>('landing')
  const [account, setAccount] = useState<TradingAccount | null>(null)
  const [authMode, setAuthMode] = useState<'signup' | 'signin'>('signup')
  const [authEmail, setAuthEmail] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [signupName, setSignupName] = useState('')
  const [signupProfile, setSignupProfile] = useState('')
  const [solanaWalletAddress, setSolanaWalletAddress] = useState('')
  const [adminEmail, setAdminEmail] = useState('')
  const [adminPassword, setAdminPassword] = useState('')
  const [markets, setMarkets] = useState<PredictionMarket[]>([])
  const [selectedMarketId, setSelectedMarketId] = useState(1)
  const [activeOutcome, setActiveOutcome] = useState<Outcome>('YES')
  const [price, setPrice] = useState(50)
  const [quantity, setQuantity] = useState(1)
  const [activeSide, setActiveSide] = useState<OrderSide>('BUY')
  const [history, setHistory] = useState<Array<Record<string, unknown>>>([])
  const [transactions, setTransactions] = useState<Array<Record<string, unknown>>>([])
  const [balances, setBalances] = useState<Array<{ asset: string; available: number }>>([])
  const [openOrders, setOpenOrders] = useState<Array<Record<string, unknown>>>([])
  const [isAdmin, setIsAdmin] = useState(false)
  const [adminStats, setAdminStats] = useState<Record<string, number>>({})
  const [adminUsers, setAdminUsers] = useState<Array<Record<string, unknown>>>([])
  const [adminTargetUserId, setAdminTargetUserId] = useState('')
  const [adminReason, setAdminReason] = useState('manual moderation')
  const [adminAsset, setAdminAsset] = useState('USD')
  const [adminDelta, setAdminDelta] = useState(0)
  const [payAsset, setPayAsset] = useState('USD')
  const [payAmount, setPayAmount] = useState(100)
  const [activeTab, setActiveTab] = useState<'trade' | 'payments' | 'history' | 'admin'>('trade')
  const [liveBook, setLiveBook] = useState<Record<Outcome, OutcomeBook> | null>(null)
  const [liveBookStatus, setLiveBookStatus] = useState('Connecting live orderbook...')

  const userId = account?.user_id ?? ''
  const selectedMarket = useMemo(
    () => markets.find((market) => market.id === selectedMarketId) ?? markets[0],
    [markets, selectedMarketId],
  )
  const activeBook = liveBook?.[activeOutcome] ?? selectedMarket?.outcomes[activeOutcome] ?? emptyBook
  const oppositeOutcome: Outcome = activeOutcome === 'YES' ? 'NO' : 'YES'

  const callApi = async <T,>(url: string, options?: RequestInit): Promise<T> => {
    const response = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...(options?.headers ?? {}) },
      ...options,
    })
    if (!response.ok) {
      const raw = await response.text()
      let message = raw || `Request failed: ${response.status}`
      try {
        const parsed = JSON.parse(raw) as { detail?: unknown }
        if (typeof parsed.detail === 'string') {
          message = parsed.detail
        } else if (Array.isArray(parsed.detail) && parsed.detail.length > 0) {
          const first = parsed.detail[0] as { msg?: string }
          if (first?.msg) message = first.msg
        }
      } catch {
        // Keep the raw server message.
      }
      throw new Error(message)
    }
    return (await response.json()) as T
  }

  const refreshMarkets = async () => {
    try {
      const response = await callApi<PredictionMarket[]>('/api/markets?status=OPEN&limit=50')
      setMarkets(response)
      if (response.length && !response.some((market) => market.id === selectedMarketId)) {
        setSelectedMarketId(response[0].id)
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Failed to load active markets.')
    }
  }

  const refreshDashboard = async () => {
    if (!account || !selectedMarket) return
    try {
      const [historyResponse, txResponse, balanceResponse, openOrdersResponse, marketResponse] = await Promise.all([
        callApi<Array<Record<string, unknown>>>(`/api/trading/history?user_id=${encodeURIComponent(userId)}&limit=20`),
        callApi<Array<Record<string, unknown>>>(
          `/api/payments/transactions?user_id=${encodeURIComponent(userId)}&limit=20`,
        ),
        callApi<Array<{ asset: string; available: number }>>(`/api/payments/balances/${encodeURIComponent(userId)}`),
        callApi<Array<Record<string, unknown>>>(
          `/api/trading/open-orders?user_id=${encodeURIComponent(userId)}&market_id=${selectedMarket.id}&limit=20`,
        ),
        callApi<PredictionMarket>(`/api/markets/${selectedMarket.id}`),
      ])
      setHistory(historyResponse)
      setTransactions(txResponse)
      setBalances(balanceResponse)
      setOpenOrders(openOrdersResponse)
      setMarkets((current) => current.map((market) => (market.id === marketResponse.id ? marketResponse : market)))
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Failed to refresh dashboard.')
    }
  }

  const refreshAdminDashboard = async () => {
    if (!account) return
    try {
      const overview = await callApi<{ stats: Record<string, number>; users: Array<Record<string, unknown>> }>(
        `/api/admin/overview?admin_user_id=${encodeURIComponent(userId)}`,
      )
      setAdminStats(overview.stats)
      setAdminUsers(overview.users)
      setIsAdmin(true)
    } catch {
      setIsAdmin(false)
      setAdminStats({})
      setAdminUsers([])
    }
  }

  useEffect(() => {
    const storedAccount = window.localStorage.getItem(ACCOUNT_STORAGE_KEY)
    if (storedAccount) {
      try {
        const parsed = JSON.parse(storedAccount) as TradingAccount
        if (parsed.user_id && parsed.user_name) {
          // eslint-disable-next-line react-hooks/set-state-in-effect
          setAccount(parsed)
          setView('dashboard')
          setStatus(`Welcome back, ${parsed.user_name}.`)
        }
      } catch {
        window.localStorage.removeItem(ACCOUNT_STORAGE_KEY)
      }
    }

    const storedAdmin = window.localStorage.getItem(ADMIN_SESSION_STORAGE_KEY)
    if (!storedAdmin) return
    try {
      const parsed = JSON.parse(storedAdmin) as { email?: string; password?: string }
      if (parsed.email && parsed.password) {
        setAdminEmail(parsed.email)
        setAdminPassword(parsed.password)
        setAppMode('admin')
        setStatus(`Admin session restored for ${parsed.email}.`)
      }
    } catch {
      window.localStorage.removeItem(ADMIN_SESSION_STORAGE_KEY)
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshMarkets()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!account) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshDashboard()
    void refreshAdminDashboard()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, selectedMarketId])

  useEffect(() => {
    if (!selectedMarket?.id) return
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/orderbooks/${selectedMarket.id}`)
    socket.onopen = () => setLiveBookStatus('Live orderbook connected.')
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as { outcomes?: Record<Outcome, OutcomeBook>; source?: string; sent_at?: string }
        if (payload.outcomes) {
          setLiveBook(payload.outcomes)
          setLiveBookStatus(`Live orderbook: ${payload.source ?? 'local'} ${payload.sent_at ?? ''}`)
        }
      } catch {
        setLiveBookStatus('Received an invalid live orderbook update.')
      }
    }
    socket.onerror = () => setLiveBookStatus('Live orderbook connection error.')
    socket.onclose = () => setLiveBookStatus('Live orderbook disconnected.')
    return () => socket.close()
  }, [selectedMarket?.id])

  const requireAccount = (market?: PredictionMarket, outcome?: Outcome) => {
    if (market) setSelectedMarketId(market.id)
    if (outcome) setActiveOutcome(outcome)
    if (!account) {
      setAuthMode('signin')
      setView('signup')
      setStatus('Sign in or create an account to place orders, split, merge, deposit, or withdraw.')
      return false
    }
    setView('dashboard')
    setActiveTab('trade')
    return true
  }

  const handleSignup = async () => {
    try {
      setIsBusy(true)
      if (authMode === 'signin') {
        const response = await callApi<{ status: string; account: TradingAccount }>('/api/users/signin', {
          method: 'POST',
          body: JSON.stringify({
            email: authEmail.trim(),
            password: authPassword,
          }),
        })
        setAccount(response.account)
        window.localStorage.setItem(ACCOUNT_STORAGE_KEY, JSON.stringify(response.account))
        setView('dashboard')
        setStatus(`Signed in as ${response.account.user_name}.`)
        await refreshDashboard()
        return
      }
      if (signupName.trim().length < 2) {
        throw new Error('Please enter your name.')
      }
      const response = await callApi<{ status: string; account: TradingAccount; starting_balance: number }>('/api/users/signup', {
        method: 'POST',
        body: JSON.stringify({
          email: authEmail.trim(),
          password: authPassword,
          user_name: signupName.trim(),
          user_profile: signupProfile.trim(),
          solana_wallet_address: solanaWalletAddress.trim(),
        }),
      })
      const nextAccount = response.account
      setAccount(nextAccount)
      window.localStorage.setItem(ACCOUNT_STORAGE_KEY, JSON.stringify(nextAccount))
      setView('dashboard')
      setStatus(`Account created. Starting balance ${response.starting_balance} USD added for test trading.`)
      await refreshDashboard()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Signup failed.')
    } finally {
      setIsBusy(false)
    }
  }

  const handleAdminLogin = async () => {
    try {
      setIsBusy(true)
      const email = adminEmail.trim().toLowerCase()
      if (!email || !adminPassword) {
        throw new Error('Enter admin email and password.')
      }
      const response = await callApi<{ access: 'grant' | 'nope'; granted: boolean }>('/api/admin/access_grant', {
        method: 'POST',
        body: JSON.stringify({ email, password: adminPassword }),
      })
      if (!response.granted) {
        throw new Error('Admin access nope.')
      }
      setStatus(`Admin access granted for ${email}.`)
      setAppMode('admin')
      window.localStorage.setItem(ADMIN_SESSION_STORAGE_KEY, JSON.stringify({ email, password: adminPassword }))
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Admin login failed.')
    } finally {
      setIsBusy(false)
    }
  }

  const submitTrade = async (action: 'buy' | 'sell' | 'limit') => {
    if (!requireAccount()) return
    if (!selectedMarket) {
      setStatus('Select a market first.')
      return
    }
    try {
      setIsBusy(true)
      if (quantity <= 0 || price <= 0) {
        throw new Error('Quantity and price must be greater than 0.')
      }
      const payload =
        action === 'limit'
          ? { user_id: userId, market_id: selectedMarket.id, outcome: activeOutcome, quantity, price, side: activeSide }
          : { user_id: userId, market_id: selectedMarket.id, outcome: activeOutcome, quantity, price }

      await callApi(`/api/trading/${action}`, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setStatus(`${action.toUpperCase()} ${activeOutcome} submitted successfully.`)
      await refreshMarkets()
      await refreshDashboard()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : `Failed to submit ${action}.`)
    } finally {
      setIsBusy(false)
    }
  }

  const submitMerge = async () => {
    if (!requireAccount() || !selectedMarket) return
    try {
      setIsBusy(true)
      await callApi('/api/trading/merge', {
        method: 'POST',
        body: JSON.stringify({
          user_id: userId,
          source_market_id: selectedMarket.id,
          target_market_id: selectedMarket.id,
          source_outcome: activeOutcome,
          target_outcome: oppositeOutcome,
          quantity,
        }),
      })
      setStatus(`Merged ${activeOutcome} into ${oppositeOutcome}.`)
      await refreshDashboard()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Merge failed.')
    } finally {
      setIsBusy(false)
    }
  }

  const submitSplit = async () => {
    if (!requireAccount() || !selectedMarket) return
    try {
      setIsBusy(true)
      await callApi('/api/trading/split', {
        method: 'POST',
        body: JSON.stringify({
          user_id: userId,
          market_id: selectedMarket.id,
          source_type: activeOutcome,
          left_type: 'YES',
          right_type: 'NO',
          ratio_left: 1,
          ratio_right: 1,
          quantity,
        }),
      })
      setStatus(`Split ${activeOutcome} into YES/NO legs.`)
      await refreshDashboard()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Split failed.')
    } finally {
      setIsBusy(false)
    }
  }

  const submitPayment = async (action: 'deposit' | 'withdraw') => {
    if (!requireAccount()) return
    try {
      setIsBusy(true)
      const idempotencyKey = crypto.randomUUID()
      await callApi(`/api/payments/${action}`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({
          user_id: userId,
          asset: payAsset,
          amount: payAmount,
          reference: `ui-${action}`,
        }),
      })
      setStatus(`${action.toUpperCase()} success with idempotency key ${idempotencyKey.slice(0, 8)}...`)
      await refreshDashboard()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : `${action} failed.`)
    } finally {
      setIsBusy(false)
    }
  }

  const signOut = () => {
    setAccount(null)
    setIsAdmin(false)
    setAdminStats({})
    setAdminUsers([])
    setView('landing')
    window.localStorage.removeItem(ACCOUNT_STORAGE_KEY)
    setStatus('Signed out. You can still browse active markets.')
  }

  const exitAdminMode = () => {
    setAppMode('trader')
    setView(account ? 'dashboard' : 'landing')
    window.localStorage.removeItem(ADMIN_SESSION_STORAGE_KEY)
    setStatus('Exited admin console.')
  }

  const runAdminFreeze = async (freeze: boolean) => {
    try {
      setIsBusy(true)
      if (!account) throw new Error('Create or restore an admin account first.')
      if (!adminTargetUserId.trim()) throw new Error('Enter target user id for moderation action.')
      await callApi('/api/admin/users/freeze', {
        method: 'POST',
        body: JSON.stringify({
          admin_user_id: userId,
          target_user_id: adminTargetUserId,
          freeze,
          reason: adminReason,
        }),
      })
      setStatus(`${freeze ? 'Freeze' : 'Unfreeze'} applied to ${adminTargetUserId}.`)
      await refreshAdminDashboard()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Admin moderation action failed.')
    } finally {
      setIsBusy(false)
    }
  }

  const runAdminRoleUpdate = async (nextIsAdmin: boolean) => {
    try {
      setIsBusy(true)
      if (!account) throw new Error('Create or restore an admin account first.')
      if (!adminTargetUserId.trim()) throw new Error('Enter target user id for role action.')
      await callApi('/api/admin/users/role', {
        method: 'POST',
        body: JSON.stringify({
          admin_user_id: userId,
          target_user_id: adminTargetUserId,
          is_admin: nextIsAdmin,
        }),
      })
      setStatus(`Role updated for ${adminTargetUserId}.`)
      await refreshAdminDashboard()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Admin role update failed.')
    } finally {
      setIsBusy(false)
    }
  }

  const runAdminBalanceAdjust = async () => {
    try {
      setIsBusy(true)
      if (!account) throw new Error('Create or restore an admin account first.')
      if (!adminTargetUserId.trim()) throw new Error('Enter target user id for balance adjustment.')
      if (!adminDelta) throw new Error('Delta must be non-zero.')
      await callApi('/api/admin/balances/adjust', {
        method: 'POST',
        body: JSON.stringify({
          admin_user_id: userId,
          target_user_id: adminTargetUserId,
          asset: adminAsset,
          delta: adminDelta,
          reason: adminReason,
        }),
      })
      setStatus(`Balance adjusted for ${adminTargetUserId}.`)
      await refreshDashboard()
      await refreshAdminDashboard()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Admin balance adjustment failed.')
    } finally {
      setIsBusy(false)
    }
  }

  const MarketCard = ({ market }: { market: PredictionMarket }) => (
    <article className="market-card">
      <div className="market-card-header">
        <div>
          <p className="eyebrow">{market.symbol}</p>
          <h3>{market.question}</h3>
        </div>
        <span className="pill">{market.source ?? market.status}</span>
      </div>
      {market.description && <p className="helper-text">{market.description}</p>}
      <div className="opinion-grid">
        {(['YES', 'NO'] as Outcome[]).map((outcome) => {
          const book = market.outcomes[outcome] ?? emptyBook
          return (
            <button
              type="button"
              className={`opinion-card ${outcome === activeOutcome && market.id === selectedMarket?.id ? 'active' : ''}`}
              key={outcome}
              onClick={() => {
                setSelectedMarketId(market.id)
                setActiveOutcome(outcome)
                if (account) setView('dashboard')
              }}
            >
              <span>{outcome}</span>
              <strong>{book.best_bid ?? '-'} bid</strong>
              <small>{book.best_ask ?? '-'} ask</small>
            </button>
          )
        })}
      </div>
      <div className="book-columns">
        <div>
          <h4>YES Bids</h4>
          <ul className="list compact-list">
            {market.outcomes.YES.bids.slice(0, 4).map((level) => (
              <li key={`yes-${level.price}`}>
                {level.quantity} @ {level.price}
              </li>
            ))}
            {!market.outcomes.YES.bids.length && <li>No YES bids</li>}
          </ul>
        </div>
        <div>
          <h4>NO Bids</h4>
          <ul className="list compact-list">
            {market.outcomes.NO.bids.slice(0, 4).map((level) => (
              <li key={`no-${level.price}`}>
                {level.quantity} @ {level.price}
              </li>
            ))}
            {!market.outcomes.NO.bids.length && <li>No NO bids</li>}
          </ul>
        </div>
      </div>
      {(market.volume || market.liquidity) && (
        <p className="helper-text">
          Volume: {market.volume?.toFixed(2) ?? '-'} | Liquidity: {market.liquidity?.toFixed(2) ?? '-'}
        </p>
      )}
      <div className="actions">
        <button type="button" onClick={() => requireAccount(market, 'YES')}>
          Trade YES
        </button>
        <button type="button" onClick={() => requireAccount(market, 'NO')}>
          Trade NO
        </button>
      </div>
    </article>
  )

  const AppTopbar = (
    <div className="topbar app-topbar">
      <div>
        <h1>Trading Platform</h1>
        <p className="subtitle">Live prediction markets backed by real market APIs</p>
      </div>
      <div className="actions">
        {account ? (
          <>
            <button type="button" className="ghost-btn" onClick={() => setView('dashboard')}>
              Dashboard
            </button>
            <button type="button" className="ghost-btn" onClick={signOut}>
              Sign out
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              onClick={() => {
                setAuthMode('signin')
                setView('signup')
              }}
            >
              Sign in
            </button>
            <button
              type="button"
              className="ghost-btn"
              onClick={() => {
                setAuthMode('signup')
                setView('signup')
              }}
            >
              Sign up
            </button>
          </>
        )}
        <button type="button" className="ghost-btn" onClick={() => setView('admin-login')}>
          Admin
        </button>
      </div>
    </div>
  )

  const LandingPage = (
    <motion.main className="auth-card dashboard public-shell" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
      {AppTopbar}
      <section className="hero-panel">
        <p className="eyebrow">Market data by real APIs</p>
        <h2>Get started with prediction markets backed by live order books.</h2>
        <p className="subtitle">
          Browse active YES/NO prices first. Sign in only when you want to trade, split, merge, or manage funds.
        </p>
        <div className="actions">
          <button type="button" onClick={() => setView('dashboard')}>
            Get Started
          </button>
          <button type="button" className="ghost-btn" onClick={() => void refreshMarkets()}>
            Refresh Markets
          </button>
        </div>
      </section>

      <section className="market-grid">
        {markets.map((market) => (
          <MarketCard key={market.id} market={market} />
        ))}
        {!markets.length && <p className="status">No active markets yet. Admin can create prediction markets.</p>}
      </section>
      <p className="status">{status}</p>
    </motion.main>
  )

  const SignupPage = (
    <motion.section className="auth-shell" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <h1>{authMode === 'signup' ? 'Create Trading Account' : 'Sign In'}</h1>
      <p className="subtitle">
        Browse markets without auth. Sign in or sign up only when you want to perform trading operations.
      </p>
      <div className="tabs">
        <button className={authMode === 'signin' ? 'tab active' : 'tab'} type="button" onClick={() => setAuthMode('signin')}>
          Sign in
        </button>
        <button className={authMode === 'signup' ? 'tab active' : 'tab'} type="button" onClick={() => setAuthMode('signup')}>
          Sign up
        </button>
      </div>
      <label>
        Email
        <input
          type="email"
          value={authEmail}
          onChange={(event) => setAuthEmail(event.target.value)}
          placeholder="you@example.com"
        />
      </label>
      <label>
        Password
        <input
          type="password"
          value={authPassword}
          onChange={(event) => setAuthPassword(event.target.value)}
          placeholder="At least 8 characters"
        />
      </label>
      {authMode === 'signup' && (
        <>
      <label>
        Name
        <input value={signupName} onChange={(event) => setSignupName(event.target.value)} placeholder="Enter your name" />
      </label>
      <label>
        Profile
        <input
          value={signupProfile}
          onChange={(event) => setSignupProfile(event.target.value)}
          placeholder="Trader profile, markets, risk notes..."
        />
      </label>
          <label>
            Solana Wallet Address
            <input
              value={solanaWalletAddress}
              onChange={(event) => setSolanaWalletAddress(event.target.value)}
              placeholder="Optional public wallet address"
            />
          </label>
        </>
      )}
      <div className="actions">
        <button
          type="button"
          onClick={() => void handleSignup()}
          disabled={
            isBusy ||
            authEmail.trim().length < 5 ||
            authPassword.length < 8 ||
            (authMode === 'signup' && signupName.trim().length < 2)
          }
        >
          {isBusy ? 'Working...' : authMode === 'signup' ? 'Create account' : 'Sign in'}
        </button>
        <button type="button" className="ghost-btn" onClick={() => setView('dashboard')}>
          Back to dashboard
        </button>
      </div>
      <p className="status">{status}</p>
    </motion.section>
  )

  const AdminLoginPage = (
    <motion.section className="auth-shell" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
      <h1>Admin Login</h1>
      <p className="subtitle">Enter admin email and password for access grant.</p>
      <label>
        Admin Email
        <input
          type="email"
          value={adminEmail}
          onChange={(event) => setAdminEmail(event.target.value)}
          placeholder="admin@company.com"
        />
      </label>
      <label>
        Admin Password
        <input
          type="password"
          value={adminPassword}
          onChange={(event) => setAdminPassword(event.target.value)}
          placeholder="Enter password"
        />
      </label>
      <div className="actions">
        <button type="button" onClick={() => void handleAdminLogin()} disabled={isBusy}>
          Admin Login
        </button>
        <button type="button" onClick={() => setView(account ? 'dashboard' : 'landing')} disabled={isBusy} className="ghost-btn">
          Back
        </button>
      </div>
      <p className="status">{status}</p>
    </motion.section>
  )

  const Dashboard = (
    <motion.main className="auth-card dashboard" initial={{ opacity: 0, y: 20, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}>
      {AppTopbar}
      <p className="wallet">
        {account ? (
          <>
            Active account: <code>{userId}</code>
          </>
        ) : (
          'Browse mode: sign in or sign up when you perform a trade.'
        )}
      </p>
      <p className="status">{status}</p>

      <div className="tabs">
        <button className={activeTab === 'trade' ? 'tab active' : 'tab'} onClick={() => setActiveTab('trade')}>
          Trade
        </button>
        <button className={activeTab === 'payments' ? 'tab active' : 'tab'} onClick={() => setActiveTab('payments')}>
          Payments
        </button>
        <button className={activeTab === 'history' ? 'tab active' : 'tab'} onClick={() => setActiveTab('history')}>
          History
        </button>
        {isAdmin && (
          <button className={activeTab === 'admin' ? 'tab active' : 'tab'} onClick={() => setActiveTab('admin')}>
            Admin
          </button>
        )}
      </div>

      <section className="panel-grid">
        <div className={`panel wide-panel ${activeTab === 'trade' ? '' : 'hidden-panel'}`}>
          <h3>Trade Controls</h3>
          <label>
            Market
            <select value={selectedMarket?.id ?? ''} onChange={(event) => setSelectedMarketId(Number(event.target.value))}>
              {markets.map((market) => (
                <option key={market.id} value={market.id}>
                  {market.symbol} - {market.question}
                </option>
              ))}
            </select>
          </label>
          {selectedMarket && <p className="helper-text">{selectedMarket.question}</p>}
          <div className="opinion-grid">
            {(['YES', 'NO'] as Outcome[]).map((outcome) => (
              <button
                type="button"
                key={outcome}
                className={`opinion-card ${activeOutcome === outcome ? 'active' : ''}`}
                onClick={() => setActiveOutcome(outcome)}
              >
                <span>{outcome}</span>
                <strong>{selectedMarket?.outcomes[outcome].best_bid ?? '-'} bid</strong>
                <small>{selectedMarket?.outcomes[outcome].best_ask ?? '-'} ask</small>
              </button>
            ))}
          </div>
          <label>
            Quantity
            <input type="number" value={quantity} min={0} onChange={(event) => setQuantity(Number(event.target.value))} />
          </label>
          <label>
            Price
            <input type="number" value={price} min={0} onChange={(event) => setPrice(Number(event.target.value))} />
          </label>
          <div className="actions">
            <button disabled={isBusy} onClick={() => void submitTrade('buy')}>
              Buy {activeOutcome}
            </button>
            <button disabled={isBusy} onClick={() => void submitTrade('sell')}>
              Sell {activeOutcome}
            </button>
            <button disabled={isBusy} onClick={() => void submitTrade('limit')}>
              Limit {activeSide} {activeOutcome}
            </button>
          </div>
          <div className="actions">
            <button disabled={isBusy} className={activeSide === 'BUY' ? '' : 'ghost-btn'} onClick={() => setActiveSide('BUY')}>
              Limit Side BUY
            </button>
            <button disabled={isBusy} className={activeSide === 'SELL' ? '' : 'ghost-btn'} onClick={() => setActiveSide('SELL')}>
              Limit Side SELL
            </button>
          </div>
          <div className="actions">
            <button disabled={isBusy} onClick={() => void submitMerge()}>
              Merge to {oppositeOutcome}
            </button>
            <button disabled={isBusy} onClick={() => void submitSplit()}>
              Split into YES/NO
            </button>
            <button disabled={isBusy} className="ghost-btn" onClick={() => void refreshDashboard()}>
              Refresh
            </button>
          </div>
        </div>

        <div className={`panel ${activeTab === 'trade' ? '' : 'hidden-panel'}`}>
          <h3>{activeOutcome} Orderbook</h3>
          <p className="helper-text">{liveBookStatus}</p>
          <div className="book-columns">
            <div>
              <h4>Bids</h4>
              <ul className="list">
                {activeBook.bids.map((level) => (
                  <li key={`bid-${level.price}`}>
                    {level.quantity} @ {level.price}
                  </li>
                ))}
                {!activeBook.bids.length && <li>No bids</li>}
              </ul>
            </div>
            <div>
              <h4>Asks</h4>
              <ul className="list">
                {activeBook.asks.map((level) => (
                  <li key={`ask-${level.price}`}>
                    {level.quantity} @ {level.price}
                  </li>
                ))}
                {!activeBook.asks.length && <li>No asks</li>}
              </ul>
            </div>
          </div>
        </div>

        <div className={`panel ${activeTab === 'payments' ? '' : 'hidden-panel'}`}>
          <h3>Payments</h3>
          <label>
            Asset
            <input value={payAsset} onChange={(event) => setPayAsset(event.target.value.toUpperCase())} />
          </label>
          <label>
            Amount
            <input type="number" value={payAmount} onChange={(event) => setPayAmount(Number(event.target.value))} />
          </label>
          <div className="actions">
            <button disabled={isBusy} onClick={() => void submitPayment('deposit')}>
              Deposit
            </button>
            <button disabled={isBusy} onClick={() => void submitPayment('withdraw')}>
              Withdraw
            </button>
            <button disabled={isBusy} className="ghost-btn" onClick={() => void refreshDashboard()}>
              Refresh
            </button>
          </div>
          <h4>Balances</h4>
          <ul className="list">
            {balances.map((balance) => (
              <li key={balance.asset}>
                {balance.asset}: {balance.available.toFixed(4)}
              </li>
            ))}
            {!balances.length && <li>No balances yet</li>}
          </ul>
        </div>

        <div className={`panel ${activeTab === 'history' ? '' : 'hidden-panel'}`}>
          <h3>History</h3>
          <ul className="list">
            {history.map((item) => (
              <li key={String(item.id)}>
                {String(item.action)} - {String(item.details)}
              </li>
            ))}
            {!history.length && <li>No history yet</li>}
          </ul>
        </div>

        <div className={`panel ${activeTab === 'history' ? '' : 'hidden-panel'}`}>
          <h3>Payment Transactions</h3>
          <ul className="list">
            {transactions.map((tx) => (
              <li key={String(tx.id)}>
                {String(tx.action)} {String(tx.amount)} {String(tx.asset)} ({String(tx.status)})
              </li>
            ))}
            {!transactions.length && <li>No transactions yet</li>}
          </ul>
        </div>

        <div className={`panel ${activeTab === 'history' ? '' : 'hidden-panel'}`}>
          <h3>Open Orders</h3>
          <ul className="list">
            {openOrders.map((order) => (
              <li key={String(order.id)}>
                #{String(order.id)} {String(order.side)} {String(order.outcome)} {String(order.remaining_quantity)} /{' '}
                {String(order.quantity)} @ {String(order.price)} ({String(order.status)})
              </li>
            ))}
            {!openOrders.length && <li>No open orders</li>}
          </ul>
        </div>

        {isAdmin && (
          <div className={`panel ${activeTab === 'admin' ? '' : 'hidden-panel'}`}>
            <h3>Admin Portal</h3>
            <p>
              Users: {adminStats.users ?? 0} | Open Orders: {adminStats.open_orders ?? 0} | Trades:{' '}
              {adminStats.trades ?? 0} | Frozen: {adminStats.frozen_users ?? 0}
            </p>
            <label>
              Target User ID
              <input value={adminTargetUserId} onChange={(event) => setAdminTargetUserId(event.target.value)} />
            </label>
            <label>
              Reason
              <input value={adminReason} onChange={(event) => setAdminReason(event.target.value)} />
            </label>
            <label>
              Asset
              <input value={adminAsset} onChange={(event) => setAdminAsset(event.target.value.toUpperCase())} />
            </label>
            <label>
              Balance Delta
              <input type="number" value={adminDelta} onChange={(event) => setAdminDelta(Number(event.target.value))} />
            </label>
            <div className="actions">
              <button disabled={isBusy} onClick={() => void runAdminFreeze(true)}>
                Freeze
              </button>
              <button disabled={isBusy} onClick={() => void runAdminFreeze(false)}>
                Unfreeze
              </button>
              <button disabled={isBusy} onClick={() => void runAdminRoleUpdate(true)}>
                Grant Admin
              </button>
              <button disabled={isBusy} onClick={() => void runAdminRoleUpdate(false)}>
                Remove Admin
              </button>
              <button disabled={isBusy} onClick={() => void runAdminBalanceAdjust()}>
                Adjust Balance
              </button>
            </div>
            <h4>Recent Users</h4>
            <ul className="list">
              {adminUsers.map((user) => (
                <li key={String(user.user_id)}>
                  {String(user.user_id)} ({String(user.user_name)}) admin={String(user.is_admin)} frozen=
                  {String(user.is_frozen)}
                </li>
              ))}
              {!adminUsers.length && <li>No users found</li>}
            </ul>
          </div>
        )}
      </section>
    </motion.main>
  )

  if (appMode === 'admin') {
    return (
      <div className="page">
        <AdminPage adminEmail={adminEmail} adminPassword={adminPassword} onExit={exitAdminMode} />
      </div>
    )
  }

  return (
    <div className="page">
      {view === 'admin-login' ? AdminLoginPage : view === 'signup' ? SignupPage : view === 'dashboard' ? Dashboard : LandingPage}
    </div>
  )
}

export default App

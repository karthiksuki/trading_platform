import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import './App.css'
import { supabase } from './supabase'
import AdminPage from './AdminPage'

const ADMIN_SESSION_STORAGE_KEY = 'trading_platform_admin_session'

declare global {
  interface Window {
    ethereum?: unknown
    solana?: {
      connect: () => Promise<unknown>
      publicKey?: {
        toString: () => string
      }
    }
    backpack?: {
      solana?: {
        connect: () => Promise<unknown>
        publicKey?: {
          toString: () => string
        }
      }
    }
    phantom?: {
      solana?: {
        connect: () => Promise<unknown>
        publicKey?: {
          toString: () => string
        }
      }
    }
  }
}

function App() {
  const [walletAddress, setWalletAddress] = useState<string>('')
  const [status, setStatus] = useState<string>('Connect with Ethereum or Solana.')
  const [isBusy, setIsBusy] = useState(false)
  const [authBusyChain, setAuthBusyChain] = useState<'ethereum' | 'solana' | null>(null)
  const [appMode, setAppMode] = useState<'trader' | 'admin'>('trader')
  const [authView, setAuthView] = useState<'wallet' | 'admin'>('wallet')
  const [adminEmail, setAdminEmail] = useState('')
  const [adminPassword, setAdminPassword] = useState('')
  const [marketId, setMarketId] = useState(1)
  const [price, setPrice] = useState(100)
  const [quantity, setQuantity] = useState(1)
  const [activeSide, setActiveSide] = useState<'BUY' | 'SELL'>('BUY')
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
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [isOnboarded, setIsOnboarded] = useState(false)
  const [onboardingName, setOnboardingName] = useState('')
  const [onboardingProfile, setOnboardingProfile] = useState('')
  const [onboardingPicture, setOnboardingPicture] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'trade' | 'payments' | 'history' | 'admin'>('trade')

  useEffect(() => {
    const stored = window.localStorage.getItem(ADMIN_SESSION_STORAGE_KEY)
    if (!stored) return
    try {
      const parsed = JSON.parse(stored) as { email?: string; password?: string }
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

  const userId = useMemo(() => {
    if (!walletAddress) return 'guest-user'
    return `wallet:${walletAddress}`
  }, [walletAddress])

  const shortWalletAddress = useMemo(() => {
    if (!walletAddress) return ''
    if (walletAddress.length <= 14) return walletAddress
    return `${walletAddress.slice(0, 8)}...${walletAddress.slice(-6)}`
  }, [walletAddress])

  useEffect(() => {
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      const identity = session?.user?.identities?.[0]
      const provider = identity?.provider?.toLowerCase() ?? ''
      const identityAddress =
        (identity?.identity_data?.wallet_address as string | undefined) ??
        (identity?.identity_data?.sub as string | undefined) ??
        ''

      setWalletAddress(identityAddress)
      if (provider) {
        setStatus(`Authenticated with ${provider}.`)
        setIsAuthenticated(true)
      }
    })

    void supabase.auth.getSession().then(({ data }) => {
      if (!data.session) return
      const identity = data.session.user.identities?.[0]
      const identityAddress =
        (identity?.identity_data?.wallet_address as string | undefined) ??
        (identity?.identity_data?.sub as string | undefined) ??
        ''
      if (identityAddress) setWalletAddress(identityAddress)
      setStatus('Already signed in.')
      setIsAuthenticated(true)
    })

    return () => subscription.unsubscribe()
  }, [])

  const handleWeb3Auth = async (chain: 'ethereum' | 'solana') => {
    try {
      setIsBusy(true)
      setAuthBusyChain(chain)
      setStatus(`Starting ${chain} sign-in...`)

      if (chain === 'ethereum' && !window.ethereum) {
        throw new Error('Ethereum wallet not found. Install MetaMask or another EVM wallet.')
      }

      if (chain === 'solana') {
        const solanaWallet =
          window.backpack?.solana ?? window.phantom?.solana ?? window.solana

        if (!solanaWallet) {
          throw new Error('Solana wallet not found. Install Phantom/Backpack/Brave wallet.')
        }
        await solanaWallet.connect()
      }

      const statement =
        'Sign in to Trading Platform to access your secure dashboard and manage orders, positions, and payments.'
      const { data, error } =
        chain === 'ethereum'
          ? await supabase.auth.signInWithWeb3({
              chain: 'ethereum',
              statement,
              wallet: window.ethereum as never,
            })
          : await (() => {
              const solanaWallet =
                window.backpack?.solana ?? window.phantom?.solana ?? window.solana
              return supabase.auth.signInWithWeb3({
                chain: 'solana',
                statement,
                wallet: solanaWallet as never,
              })
            })()

      if (error) throw error
      if (data?.session || data?.user) {
        setIsAuthenticated(true)
      }

      const { data: sessionData } = await supabase.auth.getSession()
      if (sessionData.session) {
        const identity = sessionData.session.user.identities?.[0]
        const identityAddress =
          (identity?.identity_data?.wallet_address as string | undefined) ??
          (identity?.identity_data?.sub as string | undefined) ??
          ''
        if (identityAddress) setWalletAddress(identityAddress)
        setIsAuthenticated(true)
        setStatus('Wallet sign-in successful.')
      } else {
        setStatus(`Please confirm the message in your ${chain} wallet.`)
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Web3 auth failed.'
      if (chain === 'solana' && message.toLowerCase().includes('signmessage')) {
        const solanaWallet =
          window.backpack?.solana ?? window.phantom?.solana ?? window.solana
        const fallbackAddress = solanaWallet?.publicKey?.toString?.() ?? ''

        if (fallbackAddress) {
          setWalletAddress(fallbackAddress)
          setIsAuthenticated(true)
          setStatus(
            'Connected with Solana wallet fallback mode. Complete onboarding to continue.',
          )
          return
        }

        setStatus(
          'Wallet signature unsupported by current Solana wallet session. Reconnect wallet and retry.',
        )
      } else {
        setStatus(message)
      }
    } finally {
      setIsBusy(false)
      setAuthBusyChain(null)
    }
  }

  const handleAdminLogin = async () => {
    try {
      setIsBusy(true)
      const email = adminEmail.trim().toLowerCase()
      if (!email || !adminPassword) {
        throw new Error('Enter admin email and password.')
      }
      const response = await callApi<{ access: 'grant' | 'nope'; granted: boolean }>(
        '/api/admin/access_grant',
        {
          method: 'POST',
          body: JSON.stringify({ email, password: adminPassword }),
        },
      )
      if (response.granted) {
        setStatus(`Admin access granted for ${email}.`)
        setAuthView('wallet')
        setAppMode('admin')
        window.localStorage.setItem(
          ADMIN_SESSION_STORAGE_KEY,
          JSON.stringify({ email, password: adminPassword }),
        )
      } else {
        setStatus('Admin access nope.')
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Admin login failed.')
    } finally {
      setIsBusy(false)
    }
  }

  const callApi = async <T,>(
    url: string,
    options?: RequestInit,
  ): Promise<T> => {
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
          if (first?.msg) {
            message = first.msg
          }
        }
      } catch {
        // keep fallback raw text
      }
      throw new Error(message)
    }
    return (await response.json()) as T
  }

  const refreshDashboard = async () => {
    try {
      const [historyResponse, txResponse, balanceResponse, openOrdersResponse] =
        await Promise.all([
          callApi<Array<Record<string, unknown>>>(`/api/trading/history?user_id=${encodeURIComponent(userId)}&limit=20`),
          callApi<Array<Record<string, unknown>>>(`/api/payments/transactions?user_id=${encodeURIComponent(userId)}&limit=20`),
          callApi<Array<{ asset: string; available: number }>>(
            `/api/payments/balances/${encodeURIComponent(userId)}`,
          ),
          callApi<Array<Record<string, unknown>>>(
            `/api/trading/open-orders?user_id=${encodeURIComponent(userId)}&market_id=${marketId}&limit=20`,
          ),
        ])
      setHistory(historyResponse)
      setTransactions(txResponse)
      setBalances(balanceResponse)
      setOpenOrders(openOrdersResponse)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Failed to refresh dashboard.')
    }
  }

  const refreshAdminDashboard = async () => {
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
    if (!isAuthenticated || !walletAddress) return
    const checkOnboarding = async () => {
      try {
        const response = await fetch(`/api/users/${encodeURIComponent(userId)}`)
        if (response.ok) {
          const user = (await response.json()) as {
            user_name?: string
            user_profile?: string
            profile_picture?: string
            is_admin?: number
          }
          setOnboardingName(user.user_name ?? '')
          setOnboardingProfile(user.user_profile ?? '')
          setOnboardingPicture(user.profile_picture ?? null)
          setIsAdmin((user.is_admin ?? 0) === 1)
          setIsOnboarded(true)
        } else {
          setIsOnboarded(false)
        }
      } catch {
        setIsOnboarded(false)
      }
    }
    void checkOnboarding()
  }, [isAuthenticated, userId, walletAddress])

  useEffect(() => {
    if (!isAuthenticated || !isOnboarded) return
    // This refresh is intentionally effect-driven on wallet/market changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshDashboard()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [marketId, walletAddress, isAuthenticated, isOnboarded])

  useEffect(() => {
    if (!isAuthenticated || !isOnboarded) return
    void refreshAdminDashboard()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, isOnboarded, walletAddress])

  const submitTrade = async (action: 'buy' | 'sell' | 'limit') => {
    try {
      setIsBusy(true)
      const payload =
        action === 'limit'
          ? { user_id: userId, market_id: marketId, quantity, price, side: activeSide }
          : { user_id: userId, market_id: marketId, quantity, price }

      if (quantity <= 0 || price <= 0) {
        throw new Error('Quantity and price must be greater than 0.')
      }

      await callApi(`/api/trading/${action}`, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setStatus(`${action.toUpperCase()} submitted successfully.`)
      await refreshDashboard()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : `Failed to submit ${action}.`)
    } finally {
      setIsBusy(false)
    }
  }

  const submitMerge = async () => {
    try {
      setIsBusy(true)
      await callApi('/api/trading/merge', {
        method: 'POST',
        body: JSON.stringify({
          user_id: userId,
          source_market_id: marketId,
          target_market_id: marketId + 1,
          quantity,
        }),
      })
      setStatus('Merge completed.')
      await refreshDashboard()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Merge failed.')
    } finally {
      setIsBusy(false)
    }
  }

  const submitSplit = async () => {
    try {
      setIsBusy(true)
      await callApi('/api/trading/split', {
        method: 'POST',
        body: JSON.stringify({
          user_id: userId,
          market_id: marketId,
          source_type: 'standard',
          left_type: 'left_leg',
          right_type: 'right_leg',
          ratio_left: 1,
          ratio_right: 1,
          quantity,
        }),
      })
      setStatus('Split completed.')
      await refreshDashboard()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Split failed.')
    } finally {
      setIsBusy(false)
    }
  }

  const submitPayment = async (action: 'deposit' | 'withdraw') => {
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

  const signOut = async () => {
    await supabase.auth.signOut()
    setIsAuthenticated(false)
    setIsOnboarded(false)
    setWalletAddress('')
    setIsAdmin(false)
    setAppMode('trader')
    window.localStorage.removeItem(ADMIN_SESSION_STORAGE_KEY)
    setStatus('Signed out. Connect wallet to continue.')
  }

  const exitAdminMode = () => {
    setAppMode('trader')
    setAuthView('wallet')
    window.localStorage.removeItem(ADMIN_SESSION_STORAGE_KEY)
    setStatus('Exited admin console.')
  }

  const runAdminFreeze = async (freeze: boolean) => {
    try {
      setIsBusy(true)
      if (!adminTargetUserId.trim()) {
        throw new Error('Enter target user id for moderation action.')
      }
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
      if (!adminTargetUserId.trim()) {
        throw new Error('Enter target user id for role action.')
      }
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
      if (!adminTargetUserId.trim()) {
        throw new Error('Enter target user id for balance adjustment.')
      }
      if (!adminDelta) {
        throw new Error('Delta must be non-zero.')
      }
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

  const submitOnboarding = async () => {
    try {
      setIsBusy(true)
      if (onboardingName.trim().length < 2) {
        throw new Error('Please enter your full name.')
      }
      const onboardingResult = await callApi<{ status: string; user_id: string }>('/api/users/onboard', {
        method: 'POST',
        body: JSON.stringify({
          user_id: userId,
          wallet_address: walletAddress,
          user_name: onboardingName,
          user_profile: onboardingProfile,
          profile_picture: onboardingPicture,
        }),
      })
      setIsOnboarded(true)
      if (onboardingResult.status === 'created') {
        setStatus('Onboarding complete. Welcome to your dashboard.')
      } else {
        setStatus('Account already onboarded. Loaded your existing profile.')
      }
      await refreshDashboard()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Onboarding failed.')
    } finally {
      setIsBusy(false)
    }
  }

  const handlePictureChange = (fileList: FileList | null) => {
    const file = fileList?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result
      if (typeof result === 'string') {
        setOnboardingPicture(result)
      }
    }
    reader.readAsDataURL(file)
  }

  const LoginPage = (
    <motion.section
      className="auth-shell"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
      <h1>Trading Platform Login</h1>
      <p className="subtitle">Sign in with Web3 wallet to access your trading dashboard</p>
      <p className="helper-text">
        Secure wallet authentication. No seed phrase or private key is ever requested.
      </p>
      <div className="actions">
        <button type="button" onClick={() => void handleWeb3Auth('ethereum')} disabled={isBusy}>
          {authBusyChain === 'ethereum' ? 'Processing...' : 'Sign in with wallet (Ethereum)'}
        </button>
        <button type="button" onClick={() => void handleWeb3Auth('solana')} disabled={isBusy}>
          {authBusyChain === 'solana' ? 'Processing...' : 'Sign in with wallet (Solana)'}
        </button>
      </div>
      <div className="actions">
        <button type="button" onClick={() => setAuthView('admin')} disabled={isBusy} className="ghost-btn">
          Admin
        </button>
      </div>
      <p className="status">{status}</p>
    </motion.section>
  )

  const AdminLoginPage = (
    <motion.section
      className="auth-shell"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
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
        <button type="button" onClick={() => setAuthView('wallet')} disabled={isBusy} className="ghost-btn">
          Back
        </button>
      </div>
      <p className="status">{status}</p>
    </motion.section>
  )

  const Dashboard = (
    <motion.main
      className="auth-card dashboard"
      initial={{ opacity: 0, y: 20, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.45, ease: 'easeOut' }}
    >
      <div className="topbar">
        <div>
          <h1>Trading Dashboard</h1>
          <p className="subtitle">Interactive trading, orderbook, history and payments</p>
        </div>
        <button onClick={() => void signOut()} className="ghost-btn">
          Sign out
        </button>
      </div>

      <p className="wallet">
        Active user: <code>{userId}</code>
      </p>
      <p className="status">{status}</p>
      <div className="tabs">
        <button className={activeTab === 'trade' ? 'tab active' : 'tab'} onClick={() => setActiveTab('trade')}>
          Trade
        </button>
        <button
          className={activeTab === 'payments' ? 'tab active' : 'tab'}
          onClick={() => setActiveTab('payments')}
        >
          Payments
        </button>
        <button
          className={activeTab === 'history' ? 'tab active' : 'tab'}
          onClick={() => setActiveTab('history')}
        >
          History
        </button>
        {isAdmin && (
          <button className={activeTab === 'admin' ? 'tab active' : 'tab'} onClick={() => setActiveTab('admin')}>
            Admin
          </button>
        )}
      </div>

      <section className="panel-grid">
        <div className={`panel ${activeTab === 'trade' ? '' : 'hidden-panel'}`}>
          <h3>Trade Controls</h3>
          <label>
            Market ID
            <input type="number" value={marketId} onChange={(e) => setMarketId(Number(e.target.value))} />
          </label>
          <label>
            Quantity
            <input type="number" value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} />
          </label>
          <label>
            Price
            <input type="number" value={price} onChange={(e) => setPrice(Number(e.target.value))} />
          </label>
          <div className="actions">
            <button disabled={isBusy} onClick={() => void submitTrade('buy')}>Buy</button>
            <button disabled={isBusy} onClick={() => void submitTrade('sell')}>Sell</button>
            <button disabled={isBusy} onClick={() => void submitTrade('limit')}>Limit</button>
          </div>
          <div className="actions">
            <button disabled={isBusy} onClick={() => setActiveSide('BUY')}>Limit Side BUY</button>
            <button disabled={isBusy} onClick={() => setActiveSide('SELL')}>Limit Side SELL</button>
          </div>
          <div className="actions">
            <button disabled={isBusy} onClick={() => void submitMerge()}>Merge</button>
            <button disabled={isBusy} onClick={() => void submitSplit()}>Split</button>
          </div>
        </div>

        <div className={`panel ${activeTab === 'payments' ? '' : 'hidden-panel'}`}>
          <h3>Payments (Idempotent)</h3>
          <label>
            Asset
            <input value={payAsset} onChange={(e) => setPayAsset(e.target.value.toUpperCase())} />
          </label>
          <label>
            Amount
            <input type="number" value={payAmount} onChange={(e) => setPayAmount(Number(e.target.value))} />
          </label>
          <div className="actions">
            <button disabled={isBusy} onClick={() => void submitPayment('deposit')}>Deposit</button>
            <button disabled={isBusy} onClick={() => void submitPayment('withdraw')}>Withdraw</button>
            <button disabled={isBusy} onClick={() => void refreshDashboard()}>Refresh</button>
          </div>
          <h4>Balances</h4>
          <ul className="list">
            {balances.map((balance) => (
              <li key={balance.asset}>{balance.asset}: {balance.available.toFixed(4)}</li>
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
                #{String(order.id)} {String(order.side)} {String(order.remaining_quantity)} / {String(order.quantity)} @ {String(order.price)} ({String(order.status)})
              </li>
            ))}
            {!openOrders.length && <li>No open orders</li>}
          </ul>
        </div>

        {isAdmin && (
          <div className={`panel ${activeTab === 'admin' ? '' : 'hidden-panel'}`}>
            <h3>Admin Portal</h3>
            <p>Users: {adminStats.users ?? 0} | Open Orders: {adminStats.open_orders ?? 0} | Trades: {adminStats.trades ?? 0} | Frozen: {adminStats.frozen_users ?? 0}</p>
            <label>
              Target User ID
              <input value={adminTargetUserId} onChange={(e) => setAdminTargetUserId(e.target.value)} placeholder="wallet:0x..." />
            </label>
            <label>
              Reason
              <input value={adminReason} onChange={(e) => setAdminReason(e.target.value)} />
            </label>
            <label>
              Asset
              <input value={adminAsset} onChange={(e) => setAdminAsset(e.target.value.toUpperCase())} />
            </label>
            <label>
              Balance Delta
              <input type="number" value={adminDelta} onChange={(e) => setAdminDelta(Number(e.target.value))} />
            </label>
            <div className="actions">
              <button disabled={isBusy} onClick={() => void runAdminFreeze(true)}>Freeze</button>
              <button disabled={isBusy} onClick={() => void runAdminFreeze(false)}>Unfreeze</button>
              <button disabled={isBusy} onClick={() => void runAdminRoleUpdate(true)}>Grant Admin</button>
              <button disabled={isBusy} onClick={() => void runAdminRoleUpdate(false)}>Remove Admin</button>
              <button disabled={isBusy} onClick={() => void runAdminBalanceAdjust()}>Adjust Balance</button>
            </div>
            <h4>Recent Users</h4>
            <ul className="list">
              {adminUsers.map((user) => (
                <li key={String(user.user_id)}>
                  {String(user.user_id)} ({String(user.user_name)}) admin={String(user.is_admin)} frozen={String(user.is_frozen)}
                </li>
              ))}
              {!adminUsers.length && <li>No users found</li>}
            </ul>
          </div>
        )}
      </section>
    </motion.main>
  )

  const OnboardingPage = (
    <motion.section
      className="auth-shell"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
    >
      <h1>Welcome to Trading Platform</h1>
      <p className="subtitle">Complete onboarding to create your account entry.</p>
      <p className="wallet">
        Wallet: <code>{shortWalletAddress}</code>
      </p>
      {onboardingPicture && (
        <img src={onboardingPicture} alt="Profile preview" className="profile-preview" />
      )}
      <label>
        Full Name
        <input
          value={onboardingName}
          onChange={(event) => setOnboardingName(event.target.value)}
          placeholder="Enter your name"
        />
      </label>
      <label>
        Profile
        <input
          value={onboardingProfile}
          onChange={(event) => setOnboardingProfile(event.target.value)}
          placeholder="Trader, risk profile, preferred markets..."
        />
      </label>
      <label>
        Profile Picture
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp"
          onChange={(event) => handlePictureChange(event.target.files)}
        />
      </label>
      <div className="actions">
        <button
          onClick={() => void submitOnboarding()}
          disabled={isBusy || onboardingName.trim().length < 2}
        >
          {isBusy ? 'Saving...' : 'Create account'}
        </button>
        <button className="ghost-btn" onClick={() => void signOut()}>
          Cancel
        </button>
      </div>
      <p className="status">{status}</p>
    </motion.section>
  )

  return (
    <div className="page">
      {appMode === 'admin' ? (
        <AdminPage adminEmail={adminEmail} adminPassword={adminPassword} onExit={exitAdminMode} />
      ) : !isAuthenticated ? (
        authView === 'wallet' ? LoginPage : AdminLoginPage
      ) : isOnboarded ? (
        Dashboard
      ) : (
        OnboardingPage
      )}
    </div>
  )
}

export default App

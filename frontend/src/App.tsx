import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import './App.css'
import { supabase } from './supabase'

declare global {
  interface Window {
    ethereum?: unknown
    solana?: {
      connect: () => Promise<unknown>
    }
    backpack?: {
      solana?: {
        connect: () => Promise<unknown>
      }
    }
    phantom?: {
      solana?: {
        connect: () => Promise<unknown>
      }
    }
  }
}

function App() {
  const [walletAddress, setWalletAddress] = useState<string>('')
  const [status, setStatus] = useState<string>('Connect with Ethereum or Solana.')
  const [isBusy, setIsBusy] = useState(false)
  const [authBusyChain, setAuthBusyChain] = useState<'ethereum' | 'solana' | null>(null)
  const [marketId, setMarketId] = useState(1)
  const [price, setPrice] = useState(100)
  const [quantity, setQuantity] = useState(1)
  const [activeSide, setActiveSide] = useState<'BUY' | 'SELL'>('BUY')
  const [history, setHistory] = useState<Array<Record<string, unknown>>>([])
  const [orderbook, setOrderbook] = useState<{ bids: Array<{ price: number; quantity: number }>; asks: Array<{ price: number; quantity: number }> }>({ bids: [], asks: [] })
  const [transactions, setTransactions] = useState<Array<Record<string, unknown>>>([])
  const [balances, setBalances] = useState<Array<{ asset: string; available: number }>>([])
  const [payAsset, setPayAsset] = useState('USD')
  const [payAmount, setPayAmount] = useState(100)
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [isOnboarded, setIsOnboarded] = useState(false)
  const [onboardingName, setOnboardingName] = useState('')
  const [onboardingProfile, setOnboardingProfile] = useState('')

  const userId = useMemo(() => {
    if (!walletAddress) return 'guest-user'
    return `wallet:${walletAddress.slice(0, 18)}`
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
      if (message.toLowerCase().includes('signmessage')) {
        setStatus(
          'Wallet signature was rejected or unsupported. In Solana, unlock wallet and enable signing in Backpack/Phantom, then retry.',
        )
      } else {
        setStatus(message)
      }
    } finally {
      setIsBusy(false)
      setAuthBusyChain(null)
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
      const message = await response.text()
      throw new Error(message || `Request failed: ${response.status}`)
    }
    return (await response.json()) as T
  }

  const refreshDashboard = async () => {
    try {
      const [historyResponse, orderbookResponse, txResponse, balanceResponse] =
        await Promise.all([
          callApi<Array<Record<string, unknown>>>(`/api/trading/history?user_id=${encodeURIComponent(userId)}&limit=20`),
          callApi<{ bids: Array<{ price: number; quantity: number }>; asks: Array<{ price: number; quantity: number }> }>(
            `/api/trading/orderbooks/${marketId}`,
          ),
          callApi<Array<Record<string, unknown>>>(`/api/payments/transactions?user_id=${encodeURIComponent(userId)}&limit=20`),
          callApi<Array<{ asset: string; available: number }>>(
            `/api/payments/balances/${encodeURIComponent(userId)}`,
          ),
        ])
      setHistory(historyResponse)
      setOrderbook(orderbookResponse)
      setTransactions(txResponse)
      setBalances(balanceResponse)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Failed to refresh dashboard.')
    }
  }

  useEffect(() => {
    if (!isAuthenticated || !walletAddress) return
    const checkOnboarding = async () => {
      try {
        const response = await fetch(`/api/users/${encodeURIComponent(userId)}`)
        if (response.ok) {
          const user = (await response.json()) as { user_name?: string; user_profile?: string }
          setOnboardingName(user.user_name ?? '')
          setOnboardingProfile(user.user_profile ?? '')
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

  const submitTrade = async (action: 'buy' | 'sell' | 'limit') => {
    try {
      setIsBusy(true)
      const payload =
        action === 'limit'
          ? { user_id: userId, market_id: marketId, quantity, price, side: activeSide }
          : { user_id: userId, market_id: marketId, quantity, price }

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
    setStatus('Signed out. Connect wallet to continue.')
  }

  const submitOnboarding = async () => {
    try {
      setIsBusy(true)
      await callApi('/api/users/onboard', {
        method: 'POST',
        body: JSON.stringify({
          user_id: userId,
          wallet_address: walletAddress,
          user_name: onboardingName,
          user_profile: onboardingProfile,
        }),
      })
      setIsOnboarded(true)
      setStatus('Onboarding complete. Welcome to your dashboard.')
      await refreshDashboard()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Onboarding failed.')
    } finally {
      setIsBusy(false)
    }
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
      <div className="actions">
        <button type="button" onClick={() => void handleWeb3Auth('ethereum')} disabled={isBusy}>
          {authBusyChain === 'ethereum' ? 'Processing...' : 'Sign in with wallet (Ethereum)'}
        </button>
        <button type="button" onClick={() => void handleWeb3Auth('solana')} disabled={isBusy}>
          {authBusyChain === 'solana' ? 'Processing...' : 'Sign in with wallet (Solana)'}
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

      <section className="panel-grid">
        <div className="panel">
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

        <div className="panel">
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

        <div className="panel">
          <h3>Orderbook</h3>
          <div className="book-columns">
            <div>
              <h4>Bids</h4>
              <ul className="list">
                {orderbook.bids.map((bid, index) => (
                  <li key={`bid-${index}`}>{bid.price} x {bid.quantity}</li>
                ))}
                {!orderbook.bids.length && <li>Empty</li>}
              </ul>
            </div>
            <div>
              <h4>Asks</h4>
              <ul className="list">
                {orderbook.asks.map((ask, index) => (
                  <li key={`ask-${index}`}>{ask.price} x {ask.quantity}</li>
                ))}
                {!orderbook.asks.length && <li>Empty</li>}
              </ul>
            </div>
          </div>
        </div>

        <div className="panel">
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

        <div className="panel">
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
        Wallet: <code>{walletAddress}</code>
      </p>
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
      {!isAuthenticated ? LoginPage : isOnboarded ? Dashboard : OnboardingPage}
    </div>
  )
}

export default App

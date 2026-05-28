import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import './App.css'
import { supabase } from './supabase'

declare global {
  interface Window {
    ethereum?: unknown
    solana?: {
      connect: () => Promise<unknown>
    }
  }
}

function App() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [walletAddress, setWalletAddress] = useState<string>('')
  const [status, setStatus] = useState<string>('Connect with Ethereum or Solana.')
  const [isBusy, setIsBusy] = useState(false)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const context = canvas.getContext('2d')
    if (!context) return

    const resize = () => {
      const dpr = window.devicePixelRatio || 1
      canvas.width = Math.floor(window.innerWidth * dpr)
      canvas.height = Math.floor(window.innerHeight * dpr)
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    resize()
    window.addEventListener('resize', resize)

    const points = Array.from({ length: 36 }, () => ({
      x: Math.random() * window.innerWidth,
      y: Math.random() * window.innerHeight,
      dx: (Math.random() - 0.5) * 0.4,
      dy: (Math.random() - 0.5) * 0.4,
      radius: Math.random() * 2 + 1,
    }))

    let rafId = 0
    const tick = () => {
      context.clearRect(0, 0, window.innerWidth, window.innerHeight)
      context.fillStyle = 'rgba(82, 109, 255, 0.65)'

      for (const point of points) {
        point.x += point.dx
        point.y += point.dy

        if (point.x < 0 || point.x > window.innerWidth) point.dx *= -1
        if (point.y < 0 || point.y > window.innerHeight) point.dy *= -1

        context.beginPath()
        context.arc(point.x, point.y, point.radius, 0, Math.PI * 2)
        context.fill()
      }

      context.strokeStyle = 'rgba(119, 142, 255, 0.15)'
      for (let i = 0; i < points.length; i += 1) {
        for (let j = i + 1; j < points.length; j += 1) {
          const xDistance = points[i].x - points[j].x
          const yDistance = points[i].y - points[j].y
          const distance = Math.hypot(xDistance, yDistance)
          if (distance > 120) continue
          context.beginPath()
          context.moveTo(points[i].x, points[i].y)
          context.lineTo(points[j].x, points[j].y)
          context.stroke()
        }
      }

      rafId = requestAnimationFrame(tick)
    }

    tick()

    return () => {
      cancelAnimationFrame(rafId)
      window.removeEventListener('resize', resize)
    }
  }, [])

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
    })

    return () => subscription.unsubscribe()
  }, [])

  const handleWeb3Auth = async (chain: 'ethereum' | 'solana') => {
    try {
      setIsBusy(true)
      setStatus(`Starting ${chain} sign-in...`)

      if (chain === 'ethereum' && !window.ethereum) {
        throw new Error('Ethereum wallet not found. Install MetaMask or another EVM wallet.')
      }

      if (chain === 'solana') {
        if (!window.solana) {
          throw new Error('Solana wallet not found. Install Phantom/Backpack/Brave wallet.')
        }
        await window.solana.connect()
      }

      const statement = 'I accept the Trading App terms of service.'
      const { error } =
        chain === 'ethereum'
          ? await supabase.auth.signInWithWeb3({
              chain: 'ethereum',
              statement,
            })
          : await supabase.auth.signInWithWeb3({
              chain: 'solana',
              statement,
            })

      if (error) throw error
      setStatus(`Please confirm the message in your ${chain} wallet.`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Web3 auth failed.')
    } finally {
      setIsBusy(false)
    }
  }

  return (
    <div className="page">
      <canvas ref={canvasRef} className="fx-canvas" />

      <motion.main
        className="auth-card"
        initial={{ opacity: 0, y: 20, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
      >
        <motion.h1 initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.15 }}>
          Web3 Login / Sign Up
        </motion.h1>
        <p className="subtitle">Supabase native Sign in with Web3 (SIWE / SIWS)</p>

        <div className="actions">
          <button type="button" onClick={() => void handleWeb3Auth('ethereum')} disabled={isBusy}>
            {isBusy ? 'Processing...' : 'Sign in with Ethereum'}
          </button>
          <button type="button" onClick={() => void handleWeb3Auth('solana')} disabled={isBusy}>
            {isBusy ? 'Processing...' : 'Sign in with Solana'}
          </button>
        </div>

        <p className="status">{status}</p>

        {walletAddress && (
          <motion.p
            className="wallet"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            Connected: <code>{walletAddress}</code>
          </motion.p>
        )}
      </motion.main>
    </div>
  )
}

export default App

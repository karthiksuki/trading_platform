import { createClient } from '@supabase/supabase-js'

type AppEnv = Record<string, string | undefined>

const env = import.meta.env as AppEnv

const supabaseUrl = env.VITE_SUPABASE_URL ?? env.SUPABASE_URL
const supabasePublishableKey =
  env.VITE_SUPABASE_PUBLISHABLE_KEY ?? env.SUPABASE_PUBLISHER_API_KEY

if (!supabaseUrl || !supabasePublishableKey) {
  throw new Error(
    'Missing Supabase env vars. Set VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY.',
  )
}

export const supabase = createClient(supabaseUrl, supabasePublishableKey)

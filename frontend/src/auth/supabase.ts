import { createClient, type SupabaseClient } from '@supabase/supabase-js'

import { deploymentMode } from '../config'

let supabaseClient: SupabaseClient | null = null

export function getSupabaseClient(): SupabaseClient | null {
  if (deploymentMode() !== 'trial') {
    return null
  }

  if (supabaseClient) {
    return supabaseClient
  }

  const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string | undefined
  const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined

  if (!supabaseUrl || !publishableKey) {
    throw new Error('Supabase trial auth requires VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY')
  }

  supabaseClient = createClient(supabaseUrl, publishableKey)

  return supabaseClient
}

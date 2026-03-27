export {}

declare global {
  interface Window {
    TON_CONNECT_UI?: {
      TonConnectUI: new (opts: { manifestUrl: string; buttonRootId: string | null }) => {
        wallet?: {
          account?: {
            address?: string
            chain?: string
            publicKey?: string
            [key: string]: unknown
          }
          [key: string]: unknown
        } | null
        connectionRestored?: Promise<unknown>
        connectWallet: (opts?: { tonProof?: string }) => Promise<{
          account?: {
            address?: string
            chain?: string
            publicKey?: string
            [key: string]: unknown
          }
          connectItems?: {
            tonProof?: {
              proof?: Record<string, unknown>
            }
          }
          [key: string]: unknown
        }>
        disconnect: () => Promise<void>
      }
    }
  }
}

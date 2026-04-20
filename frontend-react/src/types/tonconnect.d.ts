export {}

declare global {
  type GmzTonConnectUiInstance = {
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
    sendTransaction: (tx: {
      validUntil: number
      messages: Array<{
        address: string
        amount: string
        payload?: string
        stateInit?: string
      }>
    }) => Promise<{
      boc?: string
      transactionHash?: string
      [key: string]: unknown
    }>
    disconnect: () => Promise<void>
  }

  interface Window {
    TON_CONNECT_UI?: {
      TonConnectUI: new (opts: { manifestUrl: string; buttonRootId: string | null }) => GmzTonConnectUiInstance
    }
    __gmzTonConnectUiSingleton?: GmzTonConnectUiInstance | null
  }
}

import { useEffect, useState } from 'react'
import { getDaemonToken, setDaemonToken } from '@/services/api'
import { FieldWithTooltip } from './FieldWithTooltip'

export function DaemonAuthSection() {
  const [token, setToken] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setToken(getDaemonToken())
  }, [])

  const handleSave = () => {
    setDaemonToken(token.trim())
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold text-text-light uppercase tracking-wider">
        Daemon token
      </h3>
      <p className="text-[12px] text-text-muted">
        Stored only in this browser. Required when the server has
        HIPPOMEM_API_TOKEN or HIPPOMEM_TOKENS set. Leave empty for local-dev
        with no tokens configured.
      </p>
      <FieldWithTooltip
        label="Bearer token"
        tooltip="Matches HIPPOMEM_API_TOKEN (admin) or a HIPPOMEM_TOKENS entry. Sent as Authorization on every Studio request."
      >
        <div className="flex gap-2">
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="flex-1 px-3 py-2 rounded-lg bg-user-message border border-border-subtle text-text-light text-[13px] focus:outline-none focus:ring-1 focus:ring-primary"
            placeholder="optional — required if the daemon is locked down"
          />
          <button
            type="button"
            onClick={handleSave}
            className="px-3 py-2 rounded-lg text-[13px] font-medium bg-white/10 text-text-light hover:bg-white/15"
          >
            {saved ? 'Saved' : 'Store'}
          </button>
        </div>
      </FieldWithTooltip>
    </section>
  )
}

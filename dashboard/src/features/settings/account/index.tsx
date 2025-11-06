import { ContentSection } from '../components/content-section'
import { AgentOverview } from './agent-overview'
import { TokenManager } from './token-manager'

export function SettingsAccount() {
  return (
    <ContentSection
      title='My account'
      desc='Inspect your Valhalla agent quotas, expiry, and credentials from a single view.'
    >
      <div className='space-y-6'>
        <AgentOverview />
        <TokenManager />
      </div>
    </ContentSection>
  )
}

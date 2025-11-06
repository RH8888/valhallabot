import { ContentSection } from '../components/content-section'
import { AccountForm } from './account-form'
import { TokenManager } from './token-manager'

export function SettingsAccount() {
  return (
    <ContentSection
      title='Account'
      desc='Update your account settings. Set your preferred language and
          timezone.'
    >
      <div className='grid gap-6 lg:grid-cols-[2fr,1fr]'>
        <AccountForm />
        <TokenManager />
      </div>
    </ContentSection>
  )
}

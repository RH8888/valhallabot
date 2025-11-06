import { useSearch } from '@tanstack/react-router'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { AuthLayout } from '../auth-layout'
import { UserAuthForm } from './components/user-auth-form'

export function SignIn() {
  const { redirect } = useSearch({ from: '/(auth)/sign-in' })

  return (
    <AuthLayout>
      <Card className='gap-4'>
        <CardHeader>
          <CardTitle className='text-lg tracking-tight'>Connect with an API token</CardTitle>
          <CardDescription>
            Paste an admin or agent token to unlock the Valhalla console. Tokens never
            leave your browser except when verifying identity.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <UserAuthForm redirectTo={redirect} />
        </CardContent>
        <CardFooter>
          <p className='text-muted-foreground px-8 text-center text-sm'>
            Valhalla stores your credentials locally so you can pick up where you left off.
            Use the menu in the dashboard to rotate or revoke a token at any time.
          </p>
        </CardFooter>
      </Card>
    </AuthLayout>
  )
}

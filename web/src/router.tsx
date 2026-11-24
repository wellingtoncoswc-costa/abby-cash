import { Outlet, createRootRoute, createRoute, createRouter, type RouterHistory } from '@tanstack/react-router'
import { AuthProvider } from './auth'
import { Protected } from './layout'
import { Login, Register } from './pages/auth'
import { Billing, Cards } from './pages/billing'
import { Dashboard } from './pages/dashboard'
import { Goals, Budget } from './pages/plan'
import { Invite, Onboarding } from './pages/onboarding'
import { Channels, Settings, Spaces } from './pages/settings'
import { Transactions } from './pages/transactions'

const root = createRootRoute({ component: () => <AuthProvider><Outlet /></AuthProvider> })
const pub = <P extends string>(path: P, component: () => React.JSX.Element) => createRoute({ getParentRoute: () => root, path, component })
const layout = createRoute({ getParentRoute: () => root, id: 'app', component: Protected })
const page = <P extends string>(path: P, component: () => React.JSX.Element) => createRoute({ getParentRoute: () => layout, path, component })

const tree = root.addChildren([
  pub('/login', Login),
  pub('/cadastro', Register),
  layout.addChildren([
    page('/', Dashboard), page('/onboarding', Onboarding), page('/lancamentos', Transactions),
    page('/contas', Billing), page('/cartoes', Cards), page('/metas', Goals), page('/teto', Budget),
    page('/espacos', Spaces), page('/canais', Channels), page('/config', Settings), page('/invite/$token', Invite),
  ]),
])

export const makeRouter = (history?: RouterHistory) => createRouter({ routeTree: tree, history })
declare module '@tanstack/react-router' { interface Register { router: ReturnType<typeof makeRouter> } }

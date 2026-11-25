import { Link, useNavigate } from '@tanstack/react-router'
import { Marca } from '../marca'
import { useState, type FormEvent } from 'react'
import { api, ApiError, login } from '../api/client'
import type { S } from '../api/types'
import { useAuth } from '../auth'
import { Btn, Card, Err, Field, useSend } from '../ui'

export function Login() {
  const { setStatus } = useAuth()
  const nav = useNavigate()
  const [f, setF] = useState({ email: '', password: '', totp: '' })
  const [needTotp, setNeedTotp] = useState(false)
  const m = useSend(
    () => login(f.email, f.password, f.totp),
    () => { setStatus('in'); void nav({ to: '/' }) },
  )
  const submit = (e: FormEvent) => {
    e.preventDefault()
    m.mutate(undefined, { onError: (err) => err instanceof ApiError && err.detail === 'totp_required' && setNeedTotp(true) })
  }
  return (
    <main className="mx-auto max-w-sm p-4">
      <Marca grande />
      <form onSubmit={submit}>
        <Card title="Entrar">
          <Field label="E-mail"><input type="email" autoComplete="username" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
          <Field label="Senha"><input type="password" autoComplete="current-password" required value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
          {needTotp && <Field label="Código do autenticador (2FA)"><input inputMode="numeric" autoComplete="one-time-code" value={f.totp} onChange={(e) => setF({ ...f, totp: e.target.value })} /></Field>}
          <Err e={m.error} />
          <Btn type="submit" disabled={m.isPending} className="w-full">Entrar</Btn>
        </Card>
      </form>
      <p className="text-center text-sm">Tem um convite? <Link to="/cadastro" className="underline">Criar conta</Link></p>
    </main>
  )
}

export function Register() {
  const nav = useNavigate()
  const [f, setF] = useState({ name: '', email: '', password: '', invite_code: '' })
  const m = useSend(
    () => api('POST', '/auth/register', f satisfies S['RegisterIn']),
    () => void nav({ to: '/login' }),
  )
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  return (
    <main className="mx-auto max-w-sm p-4">
      <Marca grande />
      <form onSubmit={(e) => { e.preventDefault(); m.mutate() }}>
        <Card title="Criar conta com convite">
          <Field label="Código do convite"><input required maxLength={64} value={f.invite_code} onChange={set('invite_code')} /></Field>
          <Field label="Nome"><input required maxLength={200} autoComplete="name" value={f.name} onChange={set('name')} /></Field>
          <Field label="E-mail"><input type="email" required autoComplete="username" value={f.email} onChange={set('email')} /></Field>
          <Field label="Senha (mínimo 10 caracteres)"><input type="password" required minLength={10} maxLength={128} autoComplete="new-password" value={f.password} onChange={set('password')} /></Field>
          <Err e={m.error} />
          <Btn type="submit" disabled={m.isPending} className="w-full">Cadastrar</Btn>
        </Card>
      </form>
      <p className="text-center text-sm"><Link to="/login" className="underline">Já tenho conta</Link></p>
    </main>
  )
}

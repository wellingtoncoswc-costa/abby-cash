import { useState } from 'react'
import { api, download, logout } from '../api/client'
import type { ChannelLinkRow, LinkCode, Space } from '../api/types'
import { spaceLabel, useSpace } from '../space'
import { Btn, Card, Err, Field, useGet, useSend } from '../ui'

const CH = { telegram: 'Telegram', whatsapp_evolution: 'WhatsApp' } as const

export function LinkChannel() {
  const links = useGet<ChannelLinkRow[]>('/channels')
  const [code, setCode] = useState<(LinkCode & { channel: keyof typeof CH }) | null>(null)
  const gen = useSend((channel: keyof typeof CH) => api<LinkCode>('POST', '/channels/link-code', { channel }).then((r) => ({ ...r, channel })), setCode)
  const del = useSend((ch: string) => api('DELETE', `/channels/${ch}`))
  return (
    <>
      <ul className="mb-2">
        {(links.data ?? []).map((l) => (
          <li key={l.channel} className="flex justify-between py-1"><span>{CH[l.channel as keyof typeof CH] ?? l.channel} · {l.verified_at ? 'vinculado' : 'pendente'}</span><button type="button" className="underline" onClick={() => del.mutate(l.channel)}>Desvincular</button></li>
        ))}
        {links.data?.length === 0 && <li>Nenhum canal vinculado.</li>}
      </ul>
      <div className="flex gap-2">
        <Btn onClick={() => gen.mutate('telegram')} disabled={gen.isPending}>Vincular Telegram</Btn>
        <Btn onClick={() => gen.mutate('whatsapp_evolution')} disabled={gen.isPending}>Vincular WhatsApp</Btn>
      </div>
      <Err e={gen.error ?? del.error ?? links.error} />
      {code && (
        <div className="mt-3 rounded-md bg-slate-50 p-3 dark:bg-slate-900" role="status">
          <p>Código para {CH[code.channel]} (vale {Math.round(code.expires_in_s / 60)} min):</p>
          <p className="my-1 font-mono text-3xl tracking-widest">{code.code}</p>
          {code.deep_link ? (
            <p>Ou abra <a className="underline" href={code.deep_link} target="_blank" rel="noopener noreferrer">{code.deep_link}</a></p>
          ) : <p>{code.channel === 'telegram' ? 'Envie o código ao bot do Telegram.' : 'Envie o código ao número do WhatsApp da Abby.'}</p>}
        </div>
      )}
    </>
  )
}

export function Channels() {
  return (<><h1 className="mb-3 text-xl font-bold">Canais vinculados</h1><Card><LinkChannel /></Card></>)
}

export function Spaces() {
  const { spaces, spaceId } = useSpace()
  const [name, setName] = useState('')
  const [link, setLink] = useState('')
  const fam = useSend(() => api<Space>('POST', '/spaces/family', { name }), () => setName(''))
  const inv = useSend((id: string) => api<{ link: string }>('POST', `/spaces/${id}/invites`), (r) => setLink(r.link))
  const hasFamily = spaces.some((s) => s.type === 'family')
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Espaços e membros</h1>
      <Card title="Meus espaços">
        <ul>{spaces.map((s) => <li key={s.id} className="py-1">{spaceLabel(s)}{s.id === spaceId ? ' (ativo)' : ''}</li>)}</ul>
      </Card>
      {!hasFamily && (
        <Card title="Criar espaço familiar">
          <form onSubmit={(e) => { e.preventDefault(); fam.mutate() }}>
            <Field label="Nome da família"><input required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Err e={fam.error} />
            <Btn type="submit" disabled={fam.isPending}>Criar</Btn>
          </form>
        </Card>
      )}
      {spaces.find((s) => s.id === spaceId)?.type === 'family' && (
        <Card title="Convidar membro">
          <Btn onClick={() => inv.mutate(spaceId)} disabled={inv.isPending}>Gerar link de convite</Btn>
          <Err e={inv.error} />
          {link && <p className="mt-2 break-all" role="status">Envie este link: <code>{link}</code></p>}
        </Card>
      )}
    </>
  )
}

function Totp() {
  const [pw, setPw] = useState('')
  const [code, setCode] = useState('')
  const setup = useSend(() => api<{ secret: string; uri: string }>('POST', '/auth/2fa/setup', { password: pw }), () => setPw(''))
  const verify = useSend(() => api('POST', '/auth/2fa/verify', { code }))
  return (
    <Card title="Autenticação em dois fatores (2FA)">
      {!setup.data ? (
        <form onSubmit={(e) => { e.preventDefault(); setup.mutate() }}>
          <Field label="Senha atual"><input type="password" autoComplete="current-password" required value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
          <Err e={setup.error} />
          <Btn type="submit" disabled={setup.isPending}>Ativar 2FA</Btn>
        </form>
      ) : verify.isSuccess ? <p role="status">2FA ativado.</p> : (
        <form onSubmit={(e) => { e.preventDefault(); verify.mutate() }}>
          <p>Cadastre esta chave no aplicativo autenticador:</p>
          <p className="my-1 break-all font-mono">{setup.data.secret}</p>
          <Field label="Código de 6 dígitos"><input inputMode="numeric" required value={code} onChange={(e) => setCode(e.target.value)} /></Field>
          <Err e={verify.error} />
          <Btn type="submit" disabled={verify.isPending}>Confirmar</Btn>
        </form>
      )}
    </Card>
  )
}

function DeleteAccount() {
  const [f, setF] = useState({ password: '', totp: '' })
  const [ok, setOk] = useState(false)
  const del = useSend(() => api('DELETE', '/privacy/account', { password: f.password, totp: f.totp || null }), () => { void logout() })
  return (
    <Card title="Excluir conta">
      <p className="mb-2">Apaga seus dados pessoais de forma definitiva. Exporte antes, se quiser guardar uma cópia.</p>
      <form onSubmit={(e) => { e.preventDefault(); if (ok) del.mutate() }}>
        <Field label="Senha"><input type="password" autoComplete="current-password" required value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
        <Field label="Código 2FA (se ativo)"><input inputMode="numeric" value={f.totp} onChange={(e) => setF({ ...f, totp: e.target.value })} /></Field>
        <label className="mb-3 flex items-center gap-2"><input type="checkbox" className="!w-auto" checked={ok} onChange={(e) => setOk(e.target.checked)} />Entendo que isso não pode ser desfeito</label>
        <Err e={del.error} />
        <Btn type="submit" disabled={!ok || del.isPending} className="bg-red-700 hover:bg-red-800">Excluir minha conta</Btn>
      </form>
    </Card>
  )
}

export function Settings() {
  const [err, setErr] = useState<unknown>(null)
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Configurações</h1>
      <Card title="Preferências">
        <p>Fuso (padrão America/Sao_Paulo), horário dos lembretes (09:00), canal preferido e resumo semanal ainda não podem ser alterados pela web: a API não tem rota de atualização.</p>
      </Card>
      <Totp />
      <Card title="Privacidade">
        <Btn onClick={() => download('/privacy/export', 'abby-cash-export.zip').catch(setErr)}>Exportar meus dados (.zip)</Btn>
        <Err e={err} />
      </Card>
      <DeleteAccount />
    </>
  )
}

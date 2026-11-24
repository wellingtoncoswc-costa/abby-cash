import { useState } from 'react'
import { api, download, logout } from '../api/client'
import type { ChannelLinkRow, LinkCode, Me, Member, S, Space } from '../api/types'
import { spaceLabel, useSpace } from '../space'
import { Btn, Card, Err, Field, useGet, useMe, useSend } from '../ui'

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
        <div className="mt-3 rounded-md bg-muted p-3" role="status">
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
  const active = spaces.find((s) => s.id === spaceId)
  const members = useGet<Member[]>(spaceId ? `/spaces/${spaceId}/members` : null)
  const leave = useSend(() => api('DELETE', `/spaces/${spaceId}/members/me`))
  const kick = useSend((uid: string) => api('DELETE', `/spaces/${spaceId}/members/${uid}`))
  const me = useMe()
  const hasFamily = spaces.some((s) => s.type === 'family')
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Espaços e membros</h1>
      <Card title="Meus espaços">
        <ul>{spaces.map((s) => <li key={s.id} className="py-1">{spaceLabel(s)}{s.id === spaceId ? ' (ativo)' : ''}</li>)}</ul>
      </Card>
      <Card title="Membros do espaço ativo">
        <ul>
          {(members.data ?? []).map((m) => (
            <li key={m.user_id} className="flex justify-between py-1">
              <span>{m.name} · {m.role === 'owner' ? 'dono' : 'membro'}</span>
              {active?.type === 'family' && m.user_id !== me.data?.id && <button type="button" className="underline" aria-label={`Remover ${m.name}`} onClick={() => { if (confirm(`Remover ${m.name}?`)) kick.mutate(m.user_id) }}>Remover</button>}
            </li>
          ))}
        </ul>
        {active?.type === 'family' && <Btn className="mt-2 bg-destructive hover:bg-destructive/90" disabled={leave.isPending} onClick={() => { if (confirm('Sair deste espaço?')) leave.mutate() }}>Sair do espaço</Btn>}
        <Err e={members.error ?? leave.error ?? kick.error} />
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
      {active?.type === 'family' && (
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
        <Btn type="submit" disabled={!ok || del.isPending} className="bg-destructive hover:bg-destructive/90">Excluir minha conta</Btn>
      </form>
    </Card>
  )
}

function Prefs({ me }: { me: Me }) {
  const [f, setF] = useState({ tz: me.tz, reminder_time: me.reminder_time.slice(0, 5), preferred_channel: me.preferred_channel ?? '', weekly_digest: me.weekly_digest })
  const save = useSend(() => api('PATCH', '/me/settings', { tz: f.tz, reminder_time: f.reminder_time, preferred_channel: f.preferred_channel || null, weekly_digest: f.weekly_digest } satisfies S['SettingsIn']))
  return (
    <Card title="Preferências">
      <form onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        <Field label="Fuso horário"><input required maxLength={64} placeholder="America/Sao_Paulo" value={f.tz} onChange={(e) => setF({ ...f, tz: e.target.value })} /></Field>
        <Field label="Horário dos lembretes"><input type="time" required value={f.reminder_time} onChange={(e) => setF({ ...f, reminder_time: e.target.value })} /></Field>
        <Field label="Canal preferido"><select value={f.preferred_channel} onChange={(e) => setF({ ...f, preferred_channel: e.target.value })}><option value="">Nenhum</option><option value="telegram">Telegram</option><option value="whatsapp_evolution">WhatsApp</option></select></Field>
        <label className="mb-3 flex items-center gap-2"><input type="checkbox" className="!w-auto" checked={f.weekly_digest} onChange={(e) => setF({ ...f, weekly_digest: e.target.checked })} />Receber resumo semanal</label>
        <Err e={save.error} />
        <Btn type="submit" disabled={save.isPending}>Salvar preferências</Btn>
        {save.isSuccess && <p role="status" className="mt-2">Preferências salvas.</p>}
      </form>
    </Card>
  )
}

export function Admin() {
  const me = useMe()
  const gen = useSend(() => api<S['SignupInviteOut']>('POST', '/admin/signup-invites'))
  if (me.data && !me.data.is_admin) return <p>Apenas administradores.</p>
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Administração</h1>
      <Card title="Convite de cadastro">
        <p className="mb-2">O código aparece só uma vez e vale 7 dias.</p>
        <Btn onClick={() => gen.mutate()} disabled={gen.isPending}>Gerar convite de cadastro</Btn>
        <Err e={gen.error} />
        {gen.data && <p role="status" className="mt-2">Código: <code className="font-mono text-xl">{gen.data.code}</code> (expira em {new Date(gen.data.expires_at).toLocaleDateString('pt-BR')})</p>}
      </Card>
    </>
  )
}

export function Settings() {
  const [err, setErr] = useState<unknown>(null)
  const me = useMe()
  return (
    <>
      <h1 className="mb-3 text-xl font-bold">Configurações</h1>
      {me.data ? <Prefs me={me.data} /> : <Card title="Preferências"><p>Carregando…</p><Err e={me.error} /></Card>}
      <Totp />
      <Card title="Privacidade">
        <Btn onClick={() => download('/privacy/export', 'abby-cash-export.zip').catch(setErr)}>Exportar meus dados (.zip)</Btn>
        <Err e={err} />
      </Card>
      <DeleteAccount />
    </>
  )
}

import { BANK_LIST, bankOf } from './banks'

/** Logo do banco (simple-icons) ou monograma; chave nula/desconhecida/"outro" → inicial do nome da conta em tom neutro. Decorativo: o nome da conta já é texto. */
export function BankIcon({ institution, name = '', size = 28 }: { institution?: string | null; name?: string; size?: number }) {
  const bank = bankOf(institution)
  const known = bank && bank.color
  const text = known ? bank.mono : (name.trim()[0] ?? '?').toUpperCase()
  return (
    <span
      aria-hidden="true"
      data-bank={known ? institution : 'neutral'}
      className={`inline-flex shrink-0 items-center justify-center rounded-lg font-bold leading-none ${known ? '' : 'bg-muted text-muted-foreground'}`}
      style={{ width: size, height: size, fontSize: size * (text.length > 2 ? 0.28 : 0.38), ...(known ? { background: bank.color, color: bank.fg } : {}) }}
    >
      {known && bank.logo
        ? <svg viewBox="0 0 24 24" width={size * 0.6} height={size * 0.6} fill="currentColor" data-logo><path d={bank.logo} /></svg>
        : text}
    </span>
  )
}

/** Seletor "Banco" (select nativo não mostra imagem: o ícone fica ao lado). Valor vazio = sem banco. */
export function BankSelect({ value, onChange, name }: { value: string; onChange: (v: string) => void; name?: string }) {
  return (
    <span className="flex items-center gap-2">
      <BankIcon institution={value || null} name={name} />
      <select aria-label="Banco" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Não informado</option>
        {BANK_LIST.map((b) => <option key={b.key} value={b.key}>{b.name}</option>)}
      </select>
    </span>
  )
}

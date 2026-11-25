import { formatBRL } from './lib/money'

/** Calendário do mês: cada dia é um quadrado mais forte quanto maior o gasto (relativo ao maior dia). */
export function MapaCalor({ ano, mes, gastos }: { ano: number; mes: number; gastos: Map<number, number> }) {
  const ultimo = new Date(ano, mes, 0).getDate()
  const vazios = new Date(ano, mes - 1, 1).getDay() // domingo = 0
  const maior = Math.max(1, ...gastos.values())
  const mm = String(mes).padStart(2, '0')
  const nome = new Date(ano, mes - 1, 1).toLocaleDateString('pt-BR', { month: 'long' })
  return (
    <div role="img" aria-label={`Gastos por dia em ${nome}`} className="grid max-w-sm grid-cols-7 gap-1">
      {Array.from({ length: vazios }, (_, i) => <span key={`v${i}`} />)}
      {Array.from({ length: ultimo }, (_, i) => {
        const d = i + 1
        const v = gastos.get(d) ?? 0
        const forca = v === 0 ? 0 : Math.round(25 + (75 * v) / maior)
        const rotulo = `${String(d).padStart(2, '0')}/${mm}: ${v === 0 ? 'sem gastos' : formatBRL(v)}`
        return <span key={d} aria-label={rotulo} title={rotulo} className="aspect-square rounded-md transition-transform hover:scale-110" style={{ background: `color-mix(in oklab, var(--chart-1) ${forca}%, var(--color-muted))` }} />
      })}
    </div>
  )
}

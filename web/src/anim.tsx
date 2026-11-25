import { useEffect, useState } from 'react'

const reduzido = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

/** Número que sobe até o valor (ease-out). Sem matchMedia (testes) ou com movimento reduzido: valor direto. */
export function useCountUp(alvo: number, ms = 900): number {
  const animar = typeof matchMedia === 'function' && !reduzido()
  const [v, setV] = useState(animar ? 0 : alvo)
  useEffect(() => {
    if (!animar) return
    let raf = 0
    const t0 = performance.now()
    const passo = (t: number) => {
      const k = Math.min(1, (t - t0) / ms)
      setV(Math.round(alvo * (1 - (1 - k) ** 3)))
      if (k < 1) raf = requestAnimationFrame(passo)
    }
    raf = requestAnimationFrame(passo)
    return () => cancelAnimationFrame(raf)
  }, [alvo, ms, animar])
  return animar ? v : alvo
}

/** Anel de progresso: o arco se desenha e o ponto de luz (o da logomarca) percorre até o fim. */
export function Anel({ pct, cor }: { pct: number; cor: string }) {
  const r = 52
  const c = 2 * Math.PI * r
  const p = Math.max(0, Math.min(100, pct))
  const [on, setOn] = useState(!(typeof matchMedia === 'function' && !reduzido()))
  useEffect(() => { const id = requestAnimationFrame(() => setOn(true)); return () => cancelAnimationFrame(id) }, [])
  const ease = 'cubic-bezier(.22,1,.36,1)'
  return (
    <svg viewBox="0 0 132 132" aria-hidden="true" className="size-24 shrink-0 md:size-[132px]">
      <circle cx="66" cy="66" r={r} fill="none" stroke="currentColor" strokeOpacity=".18" strokeWidth="9" />
      <circle
        cx="66" cy="66" r={r} fill="none" stroke={cor} strokeWidth="9" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={on ? c * (1 - p / 100) : c}
        transform="rotate(-90 66 66)" style={{ transition: `stroke-dashoffset 1.1s ${ease}` }}
      />
      <g style={{ transform: `rotate(${on ? p * 3.6 : 0}deg)`, transformOrigin: '66px 66px', transition: `transform 1.1s ${ease}` }}>
        <circle cx="66" cy={66 - r} r="11" fill="var(--luz)" opacity=".28" style={{ transformOrigin: `66px ${66 - r}px`, animation: 'luz-pulso 2.4s ease-in-out 1.2s infinite' }} />
        <circle cx="66" cy={66 - r} r="5.5" fill="var(--luz)" />
      </g>
    </svg>
  )
}

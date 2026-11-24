/** Logomarca da família Abby + nome do produto (docs/design/identidade-visual.md). */
export const Marca = ({ grande = false, className = '', recolhivel = false }: { grande?: boolean; className?: string; recolhivel?: boolean }) => (
  <div className={`flex items-center gap-2 ${grande ? 'my-6 flex-col text-center' : ''} ${className}`}>
    <img src="/marca.svg" alt="" className={`${grande ? 'size-16' : 'size-8'} shrink-0 dark:brightness-125`} />
    <span className={`${grande ? 'text-2xl' : 'text-base'} whitespace-nowrap font-semibold tracking-tight ${recolhivel ? 'opacity-0 transition-opacity duration-150 group-hover/rail:opacity-100 group-focus-within/rail:opacity-100' : ''}`}>
      abby <span className="font-medium text-muted-foreground">cash</span>
    </span>
  </div>
)

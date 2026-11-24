import { useSyncExternalStore } from "react";

export type Tema = "claro" | "escuro";

const ouvintes = new Set<() => void>();
const atual = (): Tema =>
  typeof document !== "undefined" && document.documentElement.classList.contains("dark")
    ? "escuro"
    : "claro";

/** Tema da interface (claro por padrão), guardado no navegador do usuário. */
export function useTema(): [Tema, () => void] {
  const tema = useSyncExternalStore(
    (cb) => (ouvintes.add(cb), () => void ouvintes.delete(cb)),
    atual,
    () => "claro" as Tema,
  );
  const alternar = () => {
    const novo: Tema = tema === "claro" ? "escuro" : "claro";
    document.documentElement.classList.toggle("dark", novo === "escuro");
    try {
      localStorage.setItem("abby-tema", novo);
    } catch {
      // modo privado: vale só nesta sessão
    }
    ouvintes.forEach((o) => o());
  };
  return [tema, alternar];
}

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { dictionaries, type DictKey, type Lang } from "./dict";

interface I18nValue {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: DictKey, vars?: Record<string, string | number>) => string;
  /** pick a localized field from a server object (title_ru / title_kz, message_ru / message_kz …) */
  pick: (obj: Record<string, unknown> | null | undefined, base: string) => string;
}

const Ctx = createContext<I18nValue | null>(null);
const KEY = "oqumap.lang";

function initialLang(): Lang {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "ru" || v === "kz") return v;
  } catch {
    /* ignore */
  }
  return "ru";
}

export function format(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (_, k: string) => (k in vars ? String(vars[k]) : `{${k}}`));
}

export function I18nProvider({ children, initial }: { children: ReactNode; initial?: Lang }) {
  const [lang, setLangState] = useState<Lang>(initial ?? initialLang());
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(KEY, l);
    } catch {
      /* ignore */
    }
    document.documentElement.lang = l === "kz" ? "kk" : "ru";
  }, []);
  const value = useMemo<I18nValue>(() => {
    const dict = dictionaries[lang];
    return {
      lang,
      setLang,
      t: (key, vars) => format(dict[key] ?? dictionaries.ru[key] ?? key, vars),
      pick: (obj, base) => {
        if (!obj) return "";
        const v = obj[`${base}_${lang}`] ?? obj[`${base}_ru`] ?? obj[base];
        return v == null ? "" : String(v);
      },
    };
  }, [lang, setLang]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18nValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("I18nProvider missing");
  return v;
}

// Tiny typed i18n: ru is the source of keys, en must translate every one (checked by tsc).
import { createContext, useContext } from "react";
import type { Language } from "@protocol/ipc";
import { en } from "./en";
import { ru } from "./ru";

export type MessageKey = keyof typeof ru;
export type Messages = Record<MessageKey, string>;

export const dictionaries: Record<Language, Messages> = { ru, en };

export function translate(
  lang: Language,
  key: MessageKey,
  vars?: Record<string, string | number>,
): string {
  const text = dictionaries[lang][key] ?? ru[key];
  return vars ? text.replace(/\{(\w+)\}/g, (m, name: string) => String(vars[name] ?? m)) : text;
}

export const LanguageContext = createContext<Language>("ru");

export function useT() {
  const lang = useContext(LanguageContext);
  return {
    lang,
    t: (key: MessageKey, vars?: Record<string, string | number>) => translate(lang, key, vars),
  };
}

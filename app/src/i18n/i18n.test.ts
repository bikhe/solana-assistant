import { describe, expect, it } from "vitest";
import { dictionaries, translate } from ".";

describe("i18n", () => {
  it("translates every key into every language", () => {
    const keys = Object.keys(dictionaries.ru).sort();
    for (const dict of Object.values(dictionaries)) {
      expect(Object.keys(dict).sort()).toEqual(keys);
      for (const value of Object.values(dict)) expect(value.trim()).not.toBe("");
    }
  });

  it("keeps placeholders in translations", () => {
    for (const [key, ru] of Object.entries(dictionaries.ru)) {
      const vars = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort();
      expect(vars(dictionaries.en[key as keyof typeof dictionaries.en]), key).toEqual(vars(ru));
    }
  });

  it("fills placeholders", () => {
    expect(translate("ru", "wizard.progress", { n: 2, total: 5 })).toBe("Шаг 2 из 5");
    expect(translate("en", "wizard.progress", { n: 2, total: 5 })).toBe("Step 2 of 5");
  });
});

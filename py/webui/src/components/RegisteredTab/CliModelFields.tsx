/**
 * `RegisterForm` ile `EditRow` ortak alanları: ad, klasör, CLI ve model seçicileri (iki formda satır satır aynı JSX
 * kopyaydı). Yalnız sunum: durum ve kayıt/düzenleme mantığı çağıranda kalır.
 */

import { useLang } from "../../i18n/LangContext";

interface TextFieldProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}

export function TextField({ label, value, onChange, placeholder }: TextFieldProps) {
  return (
    <label>
      {label}
      <input type="text" placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

interface CliModelFieldsProps {
  cli: string;
  cliList: string[];
  onCliChange: (cli: string) => void;
  model: string;
  models: string[];
  onModelChange: (model: string) => void;
}

export function CliModelFields({ cli, cliList, onCliChange, model, models, onModelChange }: CliModelFieldsProps) {
  const { t } = useLang();
  return (
    <>
      <label>
        {t.cliLabel}
        <select value={cli} onChange={(e) => onCliChange(e.target.value)}>
          {cliList.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t.modelLabel}
        <select value={model} onChange={(e) => onModelChange(e.target.value)}>
          {models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}

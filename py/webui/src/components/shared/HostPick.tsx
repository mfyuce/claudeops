/** Tek hedef makine seçici (yerel + federasyondaki hostlar). Uzak host yoksa hiç görünmez. */
import { useLang } from "../../i18n/LangContext";
import { useStatusContext } from "../../state/StatusContext";
import { LOCAL_HOST } from "../../state/hosts";

export function HostPick({ value, onChange }: { value: string; onChange: (host: string) => void }) {
  const { t } = useLang();
  const { data } = useStatusContext();
  if (!data?.hosts.length) return null;
  return (
    <label>
      {t.hostPickLabel}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value={LOCAL_HOST}>{t.hostLocalLabel}</option>
        {data.hosts.map((h) => (
          <option key={h.name} value={h.name}>
            {h.name}
          </option>
        ))}
      </select>
    </label>
  );
}

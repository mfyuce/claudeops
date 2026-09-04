"""Handover Faz 1 — CANLI session'a wrap-up mesajı gönder (kill/respawn YOK).

2026-09-04 REWRITE (kullanıcı: "ho için ama fazladan bir ekran açıyorsun.
kullanıcı karar versin ne zaman kapatması ne zaman açmasına. sadece ho gonder
yeter"). Eski akış (kill eski proc → gnome-terminal aç → `--resume SID ...
'MSG'` → proc-presence bekle) TAMAMEN KALDIRILDI. Yeni akış: `tmux_send_keys()`
ile mesaj CANLI session'a enjekte edilir — session hiç ölmüyor, pencere hiç
kapanmıyor/açılmıyor. Context'i ne zaman sıfırlayıp yeni bir session açacağı
(eski Faz 2/3'ün işi) artık kullanıcının KENDİ, ayrı, bilinçli kararı — Faz
1'in otomatik/örtük bir devamı değil.

Canlı doğrulandı (throwaway session'lar, gerçek fleet'e dokunulmadan):
`tmux_send_keys`'in `-l`+ayrı-`Enter` mekanizması `HANDOVER_MSG_DEFAULT`'ın
TAM içeriğiyle (1204 karakter, çok satırlı, Türkçe karakterli, madde
işaretli, box-drawing unicode satırlı) test edildi — TEK bir kullanıcı
turu olarak doğru şekilde iletildi, satır satır erken-gönderim YOK (bu, açık
"multiline paste" TODO'sunun endişe ettiği senaryonun AYNISI — meğer güncel
CLI sürümünde (v2.1.260) sorun değilmiş, o TODO da bu bulguyla güncellendi).

Throttle ([[mass-faz1-ratelimit-stuck]]): rate-limit önlemek için batch_size'lı gruplar +
batch_delay arası bekleme — HÂLÂ geçerli (mesaj canlıya da gitse, session'ın onu
işlemesi yine bir API turu = yine rate-limit riski taşır, mekanizma değişse de
sunucu tarafı aynı).

Self-koruma: handover kendi atası olan claude session'ını asla hedeflemez
(process-bazlı; isim-bazlı hariç-tutma 2026-08-25'te kaldırıldı — seçim artık
web panelindeki checkbox'larla).
"""
from __future__ import annotations
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

from .discovery import find_sessions
from .needs_ho import needs_ho
from .providers import CliProvider, get_provider
from .settings import load_settings
from .spawn import find_latest_jsonl
from .tmux_backend import is_tmux_backed, tmux_send_keys

# 2026-08-25: isim-bazlı hariç-tutma (HO_EXCLUDE_BASES={co,cops,ulaksec}) KALDIRILDI
# (kullanıcı kararı: "hariç tutulma kısımlarını silelim, UI'ye checkbox ekleyelim") —
# artık neyin işlem göreceğini web panelindeki seçim belirliyor. Tek kalan koruma
# İSİM değil PROCESS bazlı: handover kendi atası olan claude session'ını (içinden
# çalıştırıldığı CLI'ı) asla öldürmez — self-kill komutu yarıda öldürür + transcript
# truncation riski ([[claude-2183-conversation-truncation]]).


def ancestor_pids() -> set:
    """Bu process'in /proc üzerinden ata-pid zinciri (parent, grandparent, ...)."""
    pids = set()
    pid = os.getpid()
    for _ in range(64):
        try:
            with open(f"/proc/{pid}/stat") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
        if ppid <= 1:
            break
        pids.add(ppid)
        pid = ppid
    return pids


def default_handover_effort(provider: CliProvider) -> str:
    """Faz 2'nin (`py/cops rc --new` — fresh bir session açan, hâlâ tek gerçek
    spawn noktası) respawn ettiği session için effort varsayımı.

    2026-09-04: Faz 1 (bu modülün `handover_faz1`'i) ve web'in tek-session
    "Handover" butonu (`web.py`'nin `_handover()`'ı) ARTIK bunu KULLANMIYOR —
    ikisi de canlı `tmux_send_keys` enjeksiyonuna geçti, hiçbir şey spawn
    etmiyor, dolayısıyla bir "yeni session'ın effort'u" seçilecek bir şey
    yok. Sadece Faz 2/`rc.py` (gerçekten fresh bir process açan tek yer)
    kullanıyor.

    Bilerek `provider.effort_levels()[-1]` (en tepe — claude'da 'max') DEĞİL:
    bu, o TEK handover turunun maliyeti değil, respawn edilen session'ın BİR
    SONRAKİ handover'a kadarki TÜM ömrü boyunca kalıcı varsayılan effort'u
    (2026-09-01, kullanıcı kararı — filodaki onlarca session'ın haftalarca
    biriken token maliyeti, tek bir turdaki uç-seviye kalite farkından daha
    ağır basıyor). 'high' yoksa (ör. ileride eklenecek bir provider'ın
    listesinde) en yükseğe düş — hiçbir provider boş liste dönmez (agy'nin
    kendi tepesi zaten 'high', bu yüzden onun için davranış değişmiyor).

    2026-09-02: kullanıcı Ayarlar'dan `handover_effort` override'ı ayarladıysa
    (settings.json) VE bu provider'ın listesinde varsa, o kullanılır — TODO L73
    ("default effort for ho... must be kept for the user, panelden kalıcı
    ayarlanabilir olmalı"). Boşsa ya da provider'ın listesinde yoksa (ör. bir
    sonraki provider'ın effort kelimeleri farklıysa) yukarıdaki sabit kural
    değişmeden devam eder — hiçbir zaman KeyError/geçersiz effort riski yok.
    """
    levels = provider.effort_levels()
    override = load_settings().get("handover_effort") or ""
    if override in levels:
        return override
    return "high" if "high" in levels else levels[-1]


HANDOVER_MSG_DEFAULT = (
    "ÖNCE: CLAUDE.md BÜYÜKLÜK OPTİMİZASYONU. Dosya her session başında context e "
    "yüklendiği için kısa ve öz olmalı.\n"
    "- Eskimiş veya artık geçerli olmayan bilgileri ayıkla; gerekiyorsa DONE.md ye taşı.\n"
    "- Tekrar eden / kod-okunarak öğrenilebilir bilgileri çıkar.\n"
    "- Hedef: bir önceki halinden belirgin şekilde küçük + daha güncel.\n"
    "SONRA aşağıdaki handover akışına devam et.\n\n"
    "═══════════════════════════════════════════════\n\n"
    "Bu konuşmayı bitiriyoruz, yeni session a geçeceğiz. KAYIT KRİTİK.\n\n"
    "Lütfen şunları kontrol et ve eksikse tamamla:\n"
    "- Konuşup da not almadığımız bir şey kaldı mı?\n"
    "- İşten işe geçtiysen eski iş TODO ya kaydedilmiş mi?\n"
    "- Her şey commit ve push lu mu? (tüm remote lara)\n"
    "- TODO.md, CLAUDE.md, DONE.md, TOBEDECIDED.md güncel mi?\n"
    "- Yeni session a hazır mıyız?\n\n"
    "DEĞİŞEN DOSYALARDAN + GIT HISTORY DEN GERÇEK İŞİ ÇIKAR:\n"
    "- Son ~1 günde değişen TÜM dosyalara bak. Ne yapılmış, ne eklenmiş, ne düzeltilmiş.\n"
    "- Çıkan her şeyi yerine yaz: biten iş → DONE.md; açık iş → TODO.md; "
    "mimari bilgi → CLAUDE.md.\n"
    "SONRA tüm güncellemeleri commit + push et (tüm remote lara).\n\n"
    "Sonunda CLAUDE.md nin sonuna "
    "\"## READY FOR HANDOVER ($(date))\" başlığıyla 5-10 satırlık özet ekle.\n"
    "Bitince \"READY FOR HANDOVER\" özetiyle dön."
)

HANDOVER_MSG_DEFAULT_EN = (
    "FIRST: CLAUDE.md SIZE OPTIMIZATION. This file gets loaded into context at the start of "
    "every session, so it should stay short and to the point.\n"
    "- Prune stale or no-longer-relevant info; move it to DONE.md if it's still worth keeping.\n"
    "- Remove anything repetitive or easily re-derived by reading the code.\n"
    "- Goal: noticeably smaller than before + more up to date.\n"
    "THEN continue with the handover flow below.\n\n"
    "═══════════════════════════════════════════════\n\n"
    "We're wrapping up this conversation and moving to a new session. RECORDING THIS IS CRITICAL.\n\n"
    "Please check the following and fill in anything missing:\n"
    "- Is there anything we discussed but never wrote down?\n"
    "- If you switched between tasks, was the earlier one recorded in TODO?\n"
    "- Is everything committed and pushed? (to all remotes)\n"
    "- Are TODO.md, CLAUDE.md, DONE.md, TOBEDECIDED.md up to date?\n"
    "- Are we ready for a new session?\n\n"
    "DERIVE THE REAL WORK FROM CHANGED FILES + GIT HISTORY:\n"
    "- Look at every file changed in roughly the last day. What was done, added, fixed.\n"
    "- Write each finding to the right place: finished work → DONE.md; open work → TODO.md; "
    "architectural info → CLAUDE.md.\n"
    "THEN commit + push all updates (to all remotes).\n\n"
    "Finally, append a 5-10 line summary to the end of CLAUDE.md under the heading "
    "\"## READY FOR HANDOVER ($(date))\".\n"
    "When done, reply with the \"READY FOR HANDOVER\" summary."
)


@dataclass
class Faz1Result:
    name: str
    status: str        # "sent" | "skipped-*" | "failed-send" | "failed-noproc" | "dry-run"
    detail: str = ""


@dataclass
class Faz1Summary:
    results: List[Faz1Result] = field(default_factory=list)

    @property
    def sent(self):
        return sum(1 for r in self.results if r.status == "sent")

    @property
    def failed(self):
        return sum(1 for r in self.results if r.status.startswith("failed"))

    @property
    def skipped(self):
        return sum(1 for r in self.results if r.status.startswith("skipped"))


def handover_faz1(
    message: str = HANDOVER_MSG_DEFAULT,
    dry_run: bool = False,
    batch_size: int = 5,
    batch_delay: float = 30.0,
    names: Optional[List[str]] = None,
) -> Faz1Summary:
    """Faz 1: wrap-up mesajını CANLI session'a gönder (kill/respawn YOK — bkz. modül docstring'i).

    `names` YOKSA (varsayılan, batch): tüm canlı session'lar hedef,
    needs_ho=False olanlar atlanır.
    `names` VARSA (tek/birkaç hedef, kullanıcı elle+bilerek seçmiş): needs_ho
    kontrolü bypass edilir (tek-hedef seçimi zaten "bunu şimdi yap" demektir).
    Her iki modda da self-koruma geçerli: bu komutun içinden çalıştığı claude
    session'ı (ata-proc) isimle bile hedeflense atlanır.
    Roster GEREKMEZ — hedef canlı proc-scan'den bulunur (kayıtlı olmayan ad-hoc
    session'lar da çalışır, ör. web panelin kendi ismi).

    batch_size + batch_delay: rate-limit önlemi ([[mass-faz1-ratelimit-stuck]]) — sadece
    batch modda anlamlı (tek/birkaç isimli çağrıda batch_size'a nadiren ulaşılır).
    """
    # Ho başında timestamp yaz — needs_ho baseline karşılaştırması için (bash _handover_stamp)
    from .paths import STATE_DIR
    import datetime
    try:
        ts_file = STATE_DIR / "last-handover.ts"
        ts_file.parent.mkdir(parents=True, exist_ok=True)
        ts_file.write_text(datetime.datetime.now().astimezone().isoformat())
    except Exception:
        pass

    sessions = find_sessions(measure_cpu=False)
    summary = Faz1Summary()

    if names:
        # Tek/birkaç isimli hedefleme: tam isim VEYA base eşleşir (rc.py deseniyle aynı,
        # trino20260823 gibi tarih-suffix'li ad-hoc isimleri de yakalar).
        wanted = set(names)
        targets = [s for s in sessions if s.name in wanted or s.base in wanted]
        found_keys = {s.name for s in targets} | {s.base for s in targets}
        for w in wanted:
            if w not in found_keys:
                print(f"  {w}: proc bulunamadı (çalışmıyor mu?)")
                summary.results.append(Faz1Result(w, "failed-noproc", "proc bulunamadı"))
    else:
        targets = list(sessions)

    # Self-koruma (isim-bazlı değil, process-bazlı): içinden çalıştığımız claude
    # session'ı (atamız) hedeflerdeyse atla — isimle bile hedeflense.
    protected = ancestor_pids()
    self_hits = [s for s in targets if s.pid in protected]
    if self_hits:
        for s in self_hits:
            print(f"  ⊘ self: {s.name} (pid={s.pid}) — bu komut onun içinden çalışıyor, atlandı")
            summary.results.append(Faz1Result(s.name, "skipped-self", "komutun atası"))
        targets = [s for s in targets if s.pid not in protected]

    # Konuşma sürmeyen provider'lar (ör. düz shell) Faz1'e katılmaz — isimle bile
    # hedeflense: burada "wrap-up" edilecek bir konuşma yok, sadece kullanıcının
    # canlı terminal'i var; onu kill+respawn etmek sürpriz veri/iş kaybı demek
    # (ör. sudo parola beklerken veya uzun bir komut çalışırken).
    no_conv = [s for s in targets if not get_provider(s.cli).has_conversation()]
    if no_conv:
        for s in no_conv:
            print(f"  ⊘ konuşma yok: {s.name} ({s.cli}) — handover kapsamı dışı, atlandı")
            summary.results.append(Faz1Result(s.name, "skipped-no-conversation", s.cli))
        targets = [s for s in targets if get_provider(s.cli).has_conversation()]
    targets.sort(key=lambda s: s.base)

    for i, session in enumerate(targets):
        # Batch delay
        if i > 0 and i % batch_size == 0 and not dry_run:
            print(f"  [{i}/{len(targets)}] batch tamamlandı, {batch_delay:.0f}s bekleniyor...")
            time.sleep(batch_delay)

        print(f"  {session.name} (pid={session.pid})...", end="", flush=True)

        # needs_ho kontrolü — SADECE batch modda (names verilmemişse). Tek-hedef seçimi
        # zaten "bunu şimdi yap" demektir.
        if not names:
            jsonl = find_latest_jsonl(session.cwd)
            jsonl_path = str(jsonl) if jsonl else None
            if not dry_run and not needs_ho(session.pid_str if hasattr(session, 'pid_str') else str(session.pid), session.cwd, jsonl_path):
                print(" skip (needs_ho=False: RFH var, repo temiz, yeni commit yok)")
                summary.results.append(Faz1Result(session.name, "skipped-no-ho"))
                continue

        if dry_run:
            print(" [dry-run] mesaj CANLI session'a gönderilecekti (kill/respawn yok)")
            summary.results.append(Faz1Result(session.name, "dry-run", "would-send-live"))
            continue

        # tmux-backed olmayan (eski/bare) bir session'a canlı enjeksiyon mümkün değil —
        # handover kapsamı dışı bırak (kill/resume'a düşmüyoruz, [[stale-tui-title-cross-suffix-resume]]
        # sınıfı sürprizlere geri dönmemek için).
        if not is_tmux_backed(session.pid):
            print(" skip (tmux-backed değil, canlı mesaj gönderilemiyor)")
            summary.results.append(Faz1Result(session.name, "skipped-not-tmux"))
            continue

        if tmux_send_keys(session.name, message):
            print(" sent (live)")
            summary.results.append(Faz1Result(session.name, "sent"))
        else:
            print(" WARN: mesaj gönderilemedi")
            summary.results.append(Faz1Result(session.name, "failed-send"))

    return summary

"""Claude TUI ekran örnekleri (test yardımcısı, test DEĞİL). Kaynaklar: giriş kutusu Claude Code 2.1.332 gerçek yakalaması
(`test_directive_delivery.box`); izin sorusu `test_steward_answer_dialog_blocked.PERM`; geçiş diyaloğunun METİNLERİ 2.1.332
ikilisindeki bileşenden ("Switch model?"/"Change effort level?", "Yes, switch to X", "No, go back"). Diyaloğun boşluk,
çerçeve ve alt yardım satırı gerçek ekranda DOĞRULANMADI (imleç/numara düzeni izin ve güven diyaloğu örnekleriyle aynı)."""

RULE = "\x1b[38;5;244m" + "─" * 40


def box(inner="", history="", footer="⏵⏵ auto mode on"):
    top = history + "\n\n" if history else ""
    return top + RULE + "\n\x1b[39m❯\xa0" + inner + "\n" + RULE + "\n\x1b[39m  " + footer


def result(text):
    return "  ⎿  " + text


def dialog(title, label, on_no=False, guide=" Enter to confirm · Esc to cancel"):
    kind = "model" if "model" in title else "effort level"
    yes, no = (" ", "❯") if on_no else ("❯", " ")
    return (RULE + "\n \x1b[1m" + "\x1b[0m \x1b[1m".join(title.split(" ")) + "\x1b[0m\n"
            " Your next response will be slower and use more tokens\n\n"
            f" This conversation is cached for the current {kind}. Switching to \x1b[1m{label}\x1b[0m means the full history gets re-read.\n\n"
            f" {yes} 1. Yes, switch to {label}\n {no} 2. No, go back\n\n{guide}\n")


IDLE = box()
SUGGESTION = box("\x1b[2mcommit this\x1b[22m")
DRAFT = box("yarım kalan yazı")
BUSY = box(footer="⏵⏵ auto mode on · esc to interrupt")
DIALOG = dialog("Switch model?", "Sonnet 5.5")
EFFORT = dialog("Change effort level?", "high")
PERMISSION = (" Bash command\n\n   git status\n\n Do you want to proceed?\n ❯ 1. Yes\n   2. Yes, and don't ask again\n"
              "   3. No, and tell Claude what to do differently (esc)\n\n Esc to cancel\n")

"""Yerel saat dilimi eşliği: `time.localtime` / `time.mktime` çıktısını yaz saati geçişleri çevresinde kaydeder.

    python3 -I parity/tz_cases.py          # fixtures/tz.json yazar
    python3 -I parity/tz_cases.py --check  # bayatsa 1
"""
import json, os, sys, time

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "tz.json")
FMT = "%Y-%m-%dT%H:%M:%S"
ZONES = ["Europe/Istanbul", "Europe/Berlin", "America/New_York", "America/Havana", "Australia/Lord_Howe", "Asia/Kathmandu"]


def transitions(first=2015, last=2028):
    """UTC ofsetinin değiştiği anlar (saniye hassasiyetinde, ikiye bölerek)."""
    t = int(time.mktime((first, 1, 1, 0, 0, 0, 0, 0, -1)))
    end = int(time.mktime((last, 1, 1, 0, 0, 0, 0, 0, -1)))
    while t < end:
        n = t + 86400
        if time.localtime(t).tm_gmtoff != time.localtime(n).tm_gmtoff:
            lo, hi = t, n
            while hi - lo > 1:
                mid = (lo + hi) // 2
                lo, hi = (mid, hi) if time.localtime(mid).tm_gmtoff == time.localtime(lo).tm_gmtoff else (lo, mid)
            yield hi
        t = n


def zone_cases(zone):
    os.environ["TZ"] = zone
    time.tzset()
    stamps = {1_800_000_000, 1_795_700_000}
    walls = set()
    for at in transitions():
        before, after = time.localtime(at - 1).tm_gmtoff, time.localtime(at).tm_gmtoff
        for d in (-3600, -1, 0, 1, 1800, 3600):
            stamps.add(at + d)
        # geçişin iki yüzündeki duvar saatleri: boşluk (ileri) ve tekrar (geri) bunların arasındadır
        a, b = sorted((at + before, at + after))
        for w in (a - 1, a, a + 1, (a + b) // 2, b - 1, b, b + 1):
            walls.add(time.strftime(FMT, time.gmtime(w)))
    return {
        "zone": zone,
        "localtime": [[t, time.strftime(FMT, time.localtime(t))] for t in sorted(stamps)],
        "mktime": [[w, time.mktime(time.strptime(w, FMT))] for w in sorted(walls)],
    }


def main():
    text = json.dumps([zone_cases(z) for z in ZONES], separators=(",", ":")) + "\n"
    if "--check" in sys.argv:
        with open(OUT, encoding="utf-8") as f:
            sys.exit(0 if f.read() == text else 1)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()

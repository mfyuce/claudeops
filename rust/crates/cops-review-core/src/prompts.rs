//! İstem üretimi ve mercek kaydı.
use crate::error::{Error, Result};
use crate::targets::FORBIDDEN_PATHS;
use regex::Regex;
use std::sync::LazyLock;

pub const BUILTIN_LENS: &str = "dry";

const LENS_TEXT_DRY_EN: &str = "Review ONLY for DRY violations: repeated code or text blocks, copy-pasted sections, near-identical functions, and the same knowledge (constants, lists, rules, messages, schemas) kept in more than one place so they can drift apart. Ignore other kinds of defects and style. Verify both copies in the code before reporting.\n";
const LENS_TEXT_DRY_TR: &str = "YALNIZ DRY ihlallerini incele: tekrar eden kod ya da metin blokları, kopyalanmış bölümler, neredeyse aynı fonksiyonlar ve aynı bilginin (sabit, liste, kural, mesaj, şema) birden çok yerde tutulup birbirinden ayrışabilmesi. Diğer kusur türlerini ve biçimi atla. Raporlamadan önce iki kopyayı da kodda doğrula.\n";
const LENS_FORMAT_EN: &str = " For this review the body MUST also name the second (repeated) location as `Also at: <path:line>` and give a consolidation proposal (where the single source of truth should live and what the callers become).";
const LENS_FORMAT_TR: &str = " Bu incelemede gövde ayrıca tekrar eden ikinci yeri `Ayrıca: <yol:satır>` olarak vermeli ve bir birleştirme önerisi içermeli (tek doğru kaynağın nerede duracağı, çağıranların ne olacağı).";

#[derive(Debug, Clone)]
struct Lens {
    name: String,
    tr: String,
    en: String,
    format_tr: String,
    format_en: String,
}

/// `LENSES` + `register_lens` karşılığı. Genel (global) durum yok: süreç tek bir kayıt tutup eklentilere verir.
#[derive(Debug, Clone)]
pub struct LensRegistry {
    lenses: Vec<Lens>,
}

impl Default for LensRegistry {
    fn default() -> Self {
        LensRegistry {
            lenses: vec![Lens {
                name: BUILTIN_LENS.into(),
                tr: LENS_TEXT_DRY_TR.into(),
                en: LENS_TEXT_DRY_EN.into(),
                format_tr: LENS_FORMAT_TR.into(),
                format_en: LENS_FORMAT_EN.into(),
            }],
        }
    }
}

fn newline_terminated(s: &str) -> String {
    if s.ends_with('\n') {
        s.to_string()
    } else {
        format!("{s}\n")
    }
}

impl LensRegistry {
    pub fn register_lens(
        &mut self,
        name: &str,
        tr: &str,
        en: &str,
        format_tr: &str,
        format_en: &str,
    ) -> Result<()> {
        // Python `$` sondaki tek satır sonunu da kabul eder.
        static NAME: LazyLock<Regex> =
            LazyLock::new(|| Regex::new(r"^[a-z][a-z0-9_-]{0,23}\n?$").unwrap());
        if !NAME.is_match(name) {
            return Err(Error::Value(format!("invalid lens name: {name:?}")));
        }
        if self.lenses.iter().any(|l| l.name == name) {
            return Err(Error::Value(format!("lens already registered: {name}")));
        }
        if crate::py::strip(tr).is_empty() || crate::py::strip(en).is_empty() {
            return Err(Error::Value("lens needs non-empty tr and en text".into()));
        }
        self.lenses.push(Lens {
            name: name.into(),
            tr: newline_terminated(tr),
            en: newline_terminated(en),
            format_tr: format_tr.into(),
            format_en: format_en.into(),
        });
        Ok(())
    }

    pub fn lenses(&self) -> Vec<&str> {
        self.lenses.iter().map(|l| l.name.as_str()).collect()
    }

    /// Salt-okunur inceleme istemi; `lens` boşsa genel inceleme.
    pub fn build_review_prompt(
        &self,
        proj: &str,
        cwd: &str,
        lang: &str,
        lens: &str,
    ) -> Result<String> {
        static EN: LazyLock<Regex> = LazyLock::new(|| {
            Regex::new(r"(?s)Find real defects:.*?before reporting it\.\n").unwrap()
        });
        static TR: LazyLock<Regex> = LazyLock::new(|| {
            Regex::new(r"(?s)Gerçek kusurları bul:.*?raporlamadan önce kodda doğrula\.\n").unwrap()
        });
        let base = general_prompt(proj, cwd, lang);
        if lens.is_empty() {
            return Ok(base);
        }
        let english = lang == "en";
        let found = self
            .lenses
            .iter()
            .find(|l| l.name == lens)
            .ok_or_else(|| Error::Value(format!("unknown review lens: {lens}")))?;
        let (text, fmt, re) = if english {
            (&found.en, &found.format_en, &*EN)
        } else {
            (&found.tr, &found.format_tr, &*TR)
        };
        let out = if re.is_match(&base) {
            re.replacen(&base, 1, regex::NoExpand(text)).into_owned()
        } else {
            format!("{base} {text}")
        };
        Ok(out + fmt)
    }
}

fn general_prompt(proj: &str, cwd: &str, lang: &str) -> String {
    let forb = FORBIDDEN_PATHS.join(", ");
    if lang == "en" {
        return format!(
            concat!(
                "You are an independent code reviewer for the project \"{proj}\" (working directory: {cwd}).\n",
                "This is a READ-ONLY review: do not create, edit, move or delete any file, do not run installers, ",
                "do not commit, push or contact the network.\n",
                "Never open, quote or summarise these paths (they may hold secrets): {forb}. If you see a secret, ",
                "do not repeat it.\n",
                "Do NOT open anything under a `reviews/` directory (earlier review reports and transcripts): ",
                "they would bias you and may contain masked secrets. Judge the code itself.\n",
                "Find real defects: correctness bugs, data loss, security problems, races, broken error handling, ",
                "stale docs that mislead. Skip style nits. Verify each claim in the code before reporting it.\n",
                "Read files whole, in large pages (read_file returns up to 1000 lines a call; read_files several ",
                "files at once), not in small windows.\n",
                "Before reporting a finding, read the whole function it is in and the code that calls or guards it; ",
                "if a guard, comment or caller already handles the case, drop the finding.\n",
                "Report each finding as a heading line exactly like\n",
                "## R-1 | P2 | path/to/file.py:123 | Short title\n",
                "(severity P1 = critical, P2 = important, P3 = minor; numbering R-1, R-2, ...) followed by a short ",
                "body: what is wrong, why, how to reproduce or check, suggested fix, and a last line ",
                "`Verified: <file:first-last line>` naming the lines you read to confirm it. ",
                "No findings: write 'NO FINDINGS'."
            ),
            proj = proj,
            cwd = cwd,
            forb = forb
        );
    }
    format!(
        concat!(
            "\"{proj}\" projesi için bağımsız bir kod gözden geçiricisisin (çalışma dizini: {cwd}).\n",
            "Bu SALT OKUNUR bir incelemedir: hiçbir dosyayı oluşturma, değiştirme, taşıma ya da silme; kurulum ",
            "çalıştırma; commit/push yapma; ağa çıkma.\n",
            "Şu yolları ASLA açma, alıntılama, özetleme (parola içerebilir): {forb}. Bir gizli değer görürsen ",
            "tekrarlama.\n",
            "`reviews/` dizininin altındaki hiçbir şeyi açma (önceki review raporları ve kayıtları): seni yanlı ",
            "yapar ve maskelenmiş gizli değer içerebilir. Yalnız kodun kendisini değerlendir.\n",
            "Gerçek kusurları bul: doğruluk hataları, veri kaybı, güvenlik, yarış durumu, bozuk hata yönetimi, ",
            "yanıltan eski belgeler. Biçim önerilerini atla. Her iddiayı raporlamadan önce kodda doğrula.\n",
            "Dosyaları küçük pencerelerle değil BÜYÜK parçalarla oku (read_file çağrı başına 1000 satıra kadar ",
            "döndürür; read_files birden çok dosyayı tek çağrıda okur).\n",
            "Bir bulguyu yazmadan önce içinde olduğu fonksiyonu baştan sona ve onu çağıran ya da koruyan kodu oku; ",
            "bir koruma, açıklama ya da çağıran durumu zaten ele alıyorsa bulguyu bırak.\n",
            "Her bulguyu tam şu biçimde bir başlık satırıyla ver:\n",
            "## R-1 | P2 | yol/dosya.py:123 | Kısa başlık\n",
            "(önem P1 = kritik, P2 = önemli, P3 = küçük; numaralama R-1, R-2, ...) ve altında kısa gövde: ne yanlış, ",
            "neden, nasıl doğrulanır, önerilen düzeltme ve son satırda doğrulamak için okuduğun satırlar: ",
            "`Doğrulama: <dosya:ilk-son satır>`. Bulgu yoksa 'BULGU YOK' yaz."
        ),
        proj = proj,
        cwd = cwd,
        forb = forb
    )
}

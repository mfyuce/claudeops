//! Süreç başına durum bağlamı (B0): TEK [`StateDocs`] (`Arc`, `docs/rs-state.md` kullanım kuralı) + salt okuma yüzü.
//!
//! R2 (tek yazar Python): `cops-state`in OKUMA yolları da yazabilir. `StateDocs::read` `dual` kipte DB'yi dosyaya uydurur
//! (`drift`/`import`), `db` kipte DB'de olmayan belgeyi dosyadan içe aktarır (`set_doc`), hata dalında `diag.log`a ekler;
//! `Roster::raw_rows` `shadow_tsv` ile `tsv_rows` tablosunu yazar; `StateDocs::store` DB'yi yazılabilir açar (WAL pragması).
//! Bu yüzden iç `StateDocs` DIŞARI VERİLMEZ: copsd uçları yalnız [`ReadDocs`] yöntemlerini görür. [`ReadDocs::read`]
//! Python `read_json` (`file_truth=True`) okuma kararını verir, ama yan etkisizdir: DB yalnız salt okunur bağlantıyla
//! ([`StateDocs::read_only_store`]) açılır, içe aktarma/uydurma/günlük YOK.
//!
//! Kurulum yan etkisiz: [`StateDocs::new`] yalnız ortamı (`CLAUDEOPS_DB_URL`) okur; dosya, dizin, DB, izin dokunulmaz
//! (`tests/state_ctx.rs` dizin içeriğini önce/sonra karşılaştırır).
use cops_state::statedocs::{read_file, Read};
use cops_state::{Backend, StateDir, StateDocs};
use std::path::Path;

pub struct ReadDocs {
    docs: StateDocs,
}

impl std::fmt::Debug for ReadDocs {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ReadDocs")
            .field("dir", self.docs.dir())
            .finish()
    }
}

impl ReadDocs {
    /// Canlı kurulum: kip ortamdan (`CLAUDEOPS_STORE_BACKEND`) ya da `settings.json` `store_backend`dan (Python ile aynı).
    pub fn new(dir: StateDir) -> ReadDocs {
        ReadDocs::from_docs(StateDocs::new(dir))
    }

    /// Verilen `StateDocs`i sarar (testler: `StateDocs::isolated`). Günlükçü stderr'e çevrilir: `diag.log` YAZILMAZ.
    pub fn from_docs(docs: StateDocs) -> ReadDocs {
        ReadDocs {
            docs: docs.with_logger(|m| eprintln!("copsd: statedocs {m}")),
        }
    }

    pub fn dir(&self) -> &StateDir {
        self.docs.dir()
    }

    /// Etkin kip (ortam > `settings.json`, 5 sn önbellek; dosya okur, yazmaz).
    pub fn backend(&self) -> Backend {
        self.docs.backend()
    }

    /// Belgenin etkin kipi (`db` istenip belge db-hazır değilse `dual`).
    pub fn effective_backend(&self, name: &str) -> Backend {
        self.docs.effective_backend(name)
    }

    /// Python `statedocs.read_json(name, path)` (`file_truth=True`) okuma kararı, YAN ETKİSİZ:
    /// - `files` ya da yol durum dizini dışında: dosya;
    /// - `dual`: dosya doğruluk kaynağı; dosya yok/bozuksa DB'deki değer (Python aynı), DB'ye uydurma YOK;
    /// - `db` (db-hazır belge): DB; satır yoksa dosya (Python burada tembel içe aktarır, biz aktarmayız); DB açılamazsa dosya.
    pub fn read(&self, name: &str, path: &Path) -> Read {
        let mode = self.docs.effective_backend(name);
        if mode == Backend::Files || !self.under_state_dir(path) {
            return read_file(path);
        }
        if mode == Backend::Dual {
            let r = read_file(path);
            if matches!(r, Read::Value(_) | Read::Lossy(_)) {
                return r;
            }
            return match self.db_doc(name) {
                Some(v) => Read::Value(v),
                None => r,
            };
        }
        match self.db_doc(name) {
            Some(v) => Read::Value(v),
            None => read_file(path),
        }
    }

    fn db_doc(&self, name: &str) -> Option<cops_state::Json> {
        let got = self.docs.read_only_store().and_then(|s| s.get_doc(name));
        match got {
            Ok(v) => v,
            Err(e) => {
                eprintln!("copsd: statedocs read {name}: {e} -> dosya");
                None
            }
        }
    }

    fn under_state_dir(&self, path: &Path) -> bool {
        use cops_state::paths::realpath;
        realpath(path).starts_with(realpath(self.docs.dir().root()))
    }
}

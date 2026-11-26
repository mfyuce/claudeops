//! `created_at_from_name` gece yarısı DST geçişi olan saat diliminde (America/Sao_Paulo: 2018-11-04 00:00 boşluk,
//! 2019-02-17 00:00 belirsiz). Ayrı test ikilisi: `TZ` süreç başında, tek iş parçacığında kurulur.
use cops_state::instances::created_at_from_name;
use cops_state::Json;

mod common;
use common::Env;

extern "C" {
    fn tzset();
}

#[test]
fn midnight_dst_matches_python() {
    if !std::path::Path::new("/usr/share/zoneinfo/America/Sao_Paulo").exists() {
        eprintln!("zoneinfo yok: atlandı");
        return;
    }
    // SAFETY: bu ikilide tek test var; başka iş parçacığı ortamı okumadan önce kurulur.
    unsafe {
        std::env::set_var("TZ", "America/Sao_Paulo");
        tzset();
    }
    let e = Env::new();
    let mut names = Vec::new();
    for y in [1990, 2008, 2015, 2016, 2017, 2018, 2019, 2024] {
        for m in [1, 2, 3, 10, 11, 12] {
            for d in 1..=31 {
                names.push(format!("a{y:04}{m:02}{d:02}"));
            }
        }
    }
    let input = Json::Array(names.iter().map(|s| Json::from(s.as_str())).collect()).to_compact();
    let out = e.py_in(
        "files",
        "from claudeops import instances as i\nprint(json.dumps([i.created_at_from_name(n) for n in json.load(sys.stdin)]))",
        &input,
    );
    let rs = Json::Array(
        names
            .iter()
            .map(|n| created_at_from_name(n).map_or(Json::Null, Json::Float))
            .collect(),
    );
    assert_eq!(rs.to_compact(), out.trim_end());
}

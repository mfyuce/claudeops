use commit_gate::*;

fn f(path: &str, added: u64, deleted: u64) -> FileStat {
    FileStat { path: path.into(), added, deleted }
}

const TBD: &str = "## #318 (25 Kas): ince kanca\n- Python-istisnası: ONAYLI (sahip, 2026-11-25)\n\n## #319 (25 Kas): başka\n- Python-istisnası: ONAYLI (sahip adına cops)\n### 320) eski biçim\nPython-istisnası: ONAYLI (sahip, 2026-11-25)\n";

#[test]
fn kinds() {
    for m in ["feat: x", "feat(steward): x", "feat!: x", "FEAT: x", "# yorum\n\nfixup! feat: x"] {
        assert_eq!(kind(m), Kind::Feat, "{m}");
    }
    assert_eq!(kind("fix(review): x"), Kind::Fix);
    for m in ["feature: x", "test: feat: x", "docs: x", "fixtures: x", ""] {
        assert_eq!(kind(m), Kind::Other, "{m}");
    }
}

#[test]
fn feat_growing_python_is_rejected() {
    for p in ["py/claudeops/x.py", "claudeops_enterprise/a/b.py", "py/tests/test_x.py"] {
        assert_eq!(evaluate("feat: x", &[f(p, 3, 1)], "", Some(TBD)).errors.len(), 1, "{p}");
    }
}

#[test]
fn feat_outside_scope_or_shrinking_passes() {
    let files = [f("rust/a.rs", 90, 0), f("py/claudeops/x.py", 2, 9), f("py/webui/a.tsx", 5, 0), f("scripts/a.py", 5, 0)];
    assert_eq!(evaluate("feat: x", &files, "", None), Verdict::default());
    assert_eq!(evaluate("chore: x", &[f("py/a.py", 9, 0)], "", None), Verdict::default());
}

#[test]
fn exception_needs_owner_approved_tbd() {
    let grow = [f("py/a.py", 9, 0)];
    let msg = |n: &str| format!("feat: x\n\ngövde\n\nPython-exception: TBD#{n}\n");
    for ok in ["318", "320"] {
        let v = evaluate(&msg(ok), &grow, "", Some(TBD));
        assert!(v.errors.is_empty() && v.warnings.len() == 1, "{ok}: {v:?}");
    }
    for bad in ["319", "999", "31"] {
        assert_eq!(evaluate(&msg(bad), &grow, "", Some(TBD)).errors.len(), 1, "{bad}");
    }
    assert_eq!(evaluate(&msg("318"), &grow, "", None).errors.len(), 1);
    // yorum satırındaki trailer sayılmaz
    assert_eq!(evaluate("feat: x\n# Python-exception: TBD#318\n", &grow, "", Some(TBD)).errors.len(), 1);
}

#[test]
fn fix_warns_only_on_new_public_surface() {
    let diff = "diff --git a/py/a.py b/py/a.py\n--- a/py/a.py\n+++ b/py/a.py\n@@ -1 +1,9 @@\n-def moved(x):\n+def moved(x, y):\n+def fresh(a):\n+    async def method(self):\n+def _private():\n+        def inner():\n+    if p == \"/api/new\":\ndiff --git a/py/tests/t.py b/py/tests/t.py\n--- a/py/tests/t.py\n+++ b/py/tests/t.py\n@@ -0,0 +1 @@\n+def helper():\n";
    assert_eq!(new_public(diff), ["işlev fresh", "işlev method", "uç /api/new"]);
    let v = evaluate("fix: x", &[], diff, None);
    assert!(v.errors.is_empty() && v.warnings.len() == 1);
}

#[test]
fn numstat_with_rename_and_binary() {
    let raw = "3\t1\tpy/a.py\0-\t-\timg.png\05\t0\t\0old.py\0py/new.py\0";
    assert_eq!(parse_numstat(raw), [f("py/a.py", 3, 1), f("img.png", 0, 0), f("py/new.py", 5, 0)]);
}

use cops_steward_core::types::*;

/// py: SessionView.project
#[test]
fn session_view_project() {
    let mut v = SessionView { name: "a2".into(), ..Default::default() };
    assert_eq!(v.project(), "a2");
    v.blueprint = Some(String::new()); // Python `or`: boş blueprint de ada düşer
    assert_eq!(v.project(), "a2");
    v.blueprint = Some("a".into());
    assert_eq!(v.project(), "a");
}

use std::path::PathBuf;

fn main() {
    let manifest = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("manifest directory"));
    let project_root = manifest
        .parent()
        .and_then(|desktop| desktop.parent())
        .expect("Jarvis project root")
        .canonicalize()
        .expect("canonical Jarvis project root");
    println!(
        "cargo:rustc-env=JARVIS_PROJECT_ROOT={}",
        project_root.display()
    );
    println!("cargo:rerun-if-changed=../../scripts/supervise_assistant.py");
    tauri_build::build();
}

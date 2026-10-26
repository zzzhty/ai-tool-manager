use serde_json::Value;
use std::{env, fs, path::PathBuf};

fn main() {
    let registry = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap())
        .join("../../harness/.agents/harnesses/registry.json");
    println!("cargo:rerun-if-changed={}", registry.display());
    let data: Value = serde_json::from_slice(&fs::read(registry).unwrap()).unwrap();
    let mut generated = String::from("pub const TOOLS: &[ToolDescriptor] = &[\n");
    for (id, spec) in data["harnesses"].as_object().unwrap() {
        let label = spec["displayName"].as_str().unwrap();
        let skills = spec["localSkillsPath"]
            .as_str()
            .or_else(|| spec["skills"]["relativePath"].as_str())
            .expect("tool must declare a local skill path");
        let aliases: Vec<_> = spec["aliases"]
            .as_array()
            .into_iter()
            .flatten()
            .map(|alias| alias.as_str().unwrap())
            .collect();
        generated.push_str(&format!("ToolDescriptor {{ id: {id:?}, label: {label:?}, aliases: &{aliases:?}, skills: {skills:?}, candidates: &["));
        for candidate in spec["root"]["candidates"].as_array().unwrap() {
            let source = candidate["source"].as_str().unwrap();
            assert!(matches!(
                source,
                "environment" | "user-home" | "openclaw-state"
            ));
            let append = candidate["append"].as_str().unwrap();
            let env = candidate["name"].as_str().unwrap_or("");
            generated.push_str(&format!(
                "RootCandidate {{ source: {source:?}, append: {append:?}, env: {env:?} }},"
            ));
        }
        generated.push_str("] },\n");
    }
    generated.push_str("];\n");
    fs::write(
        PathBuf::from(env::var_os("OUT_DIR").unwrap()).join("tools.rs"),
        generated,
    )
    .unwrap();
}

//! Explicit developer operation after source tests and plugin-generation update.
use atm_core::distribution::source;
use std::path::PathBuf;
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or("usage: seal_distribution <absolute harness path>")?;
    source::seal(&root)?;
    let bundle = source::load(&root)?;
    println!(
        "{} {} files, {} skills",
        bundle.identity,
        bundle.files.len(),
        bundle.catalog["skills"].as_array().map_or(0, Vec::len)
    );
    Ok(())
}

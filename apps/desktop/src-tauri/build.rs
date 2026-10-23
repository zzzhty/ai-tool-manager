// Reproducible source-only icon: no opaque binary input in the audited source.
fn write_windows_icon() {
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("windows") {
        return;
    }
    let size = 32u32;
    let dib_size = 40 + size * size * 4 + size * 4;
    let mut bytes = Vec::new();
    for value in [0u16, 1, 1] {
        bytes.extend(value.to_le_bytes());
    }
    bytes.extend([32, 32, 0, 0]);
    bytes.extend(1u16.to_le_bytes());
    bytes.extend(32u16.to_le_bytes());
    bytes.extend(dib_size.to_le_bytes());
    bytes.extend(22u32.to_le_bytes());
    bytes.extend(40u32.to_le_bytes());
    bytes.extend(size.to_le_bytes());
    bytes.extend((size * 2).to_le_bytes());
    bytes.extend(1u16.to_le_bytes());
    bytes.extend(32u16.to_le_bytes());
    bytes.extend(0u32.to_le_bytes());
    bytes.extend((size * size * 4).to_le_bytes());
    for _ in 0..4 {
        bytes.extend(0u32.to_le_bytes());
    }
    for y in (0i32..32).rev() {
        for x in 0i32..32 {
            let ring = (x - 12).pow(2) + (y - 11).pow(2);
            let key = (16..=49).contains(&ring)
                || ((14..=24).contains(&y) && (10..=13).contains(&x))
                || ((21..=24).contains(&y) && (10..=18).contains(&x));
            bytes.extend(if key {
                [190, 234, 215, 255]
            } else {
                [58, 51, 36, 255]
            });
        }
    }
    bytes.extend([0u8; 128]);
    let icons = std::path::Path::new("icons");
    std::fs::create_dir_all(icons).expect("create generated icon directory");
    let path = icons.join("icon.ico");
    if !std::fs::read(&path).is_ok_and(|existing| existing == bytes) {
        std::fs::write(path, bytes).expect("write generated icon");
    }
}
fn main() {
    if std::env::var_os("CARGO_FEATURE_DESKTOP").is_none() {
        return;
    }
    write_windows_icon();
    write_png_icon();
    write_macos_icon();
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "snapshot",
            "save_key",
            "delete_key",
            "save_target",
            "delete_target",
            "preview",
            "apply_preview",
            "cancel_preview",
            "list_backups",
            "preview_rollback",
            "infer_template",
            "save_template",
            "delete_template",
            "initialize_storage",
            "configure_codex_cli",
            "disconnect_codex_cli",
            "query_codex_usage",
            "query_glm_usage",
            "omh_status",
            "omh_capabilities",
            "omh_diagnose",
            "omh_execute",
            "skills_inventory",
            "skills_install",
            "skills_uninstall",
            "skills_restore",
            "skills_purge",
            "skills_copy",
            "report_linux_smoke",
        ]),
    ))
    .expect("Tauri build configuration failed");
}

fn write_png_icon() {
    if !matches!(
        std::env::var("CARGO_CFG_TARGET_OS").as_deref(),
        Ok("linux" | "macos")
    ) {
        return;
    }
    let mut pixels = Vec::with_capacity(32 * 32 * 4);
    for y in 0i32..32 {
        for x in 0i32..32 {
            let ring = (x - 12).pow(2) + (y - 11).pow(2);
            let key = (16..=49).contains(&ring)
                || ((14..=24).contains(&y) && (10..=13).contains(&x))
                || ((21..=24).contains(&y) && (10..=18).contains(&x));
            pixels.extend(if key {
                [215, 234, 190, 255]
            } else {
                [36, 51, 58, 255]
            });
        }
    }
    std::fs::create_dir_all("icons").expect("create generated icon directory");
    let mut bytes = Vec::new();
    {
        let mut encoder = png::Encoder::new(&mut bytes, 32, 32);
        encoder.set_color(png::ColorType::Rgba);
        encoder.set_depth(png::BitDepth::Eight);
        encoder
            .write_header()
            .expect("encode generated icon")
            .write_image_data(&pixels)
            .expect("write generated pixels");
    }
    let path = std::path::Path::new("icons/icon.png");
    if !std::fs::read(path).is_ok_and(|existing| existing == bytes) {
        std::fs::write(path, bytes).expect("write generated Linux icon");
    }
}

fn write_macos_icon() {
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("macos") {
        return;
    }
    // Native ICNS container with deterministic PNG elements. No opaque source
    // binary, external image tool, signing identity or Keychain access is needed.
    let mut elements = Vec::new();
    for (size, kind) in [
        (128u32, b"ic07"),
        (256, b"ic08"),
        (512, b"ic09"),
        (1024, b"ic10"),
    ] {
        let mut pixels = Vec::with_capacity((size * size * 4) as usize);
        for y in 0..size {
            for x in 0..size {
                let x = (x * 32 / size) as i32;
                let y = (y * 32 / size) as i32;
                let ring = (x - 12).pow(2) + (y - 11).pow(2);
                let key = (16..=49).contains(&ring)
                    || ((14..=24).contains(&y) && (10..=13).contains(&x))
                    || ((21..=24).contains(&y) && (10..=18).contains(&x));
                pixels.extend(if key {
                    [190, 234, 215, 255]
                } else {
                    [58, 51, 36, 255]
                });
            }
        }
        let mut encoded = Vec::new();
        {
            let mut encoder = png::Encoder::new(&mut encoded, size, size);
            encoder.set_color(png::ColorType::Rgba);
            encoder.set_depth(png::BitDepth::Eight);
            encoder
                .write_header()
                .expect("encode macOS icon")
                .write_image_data(&pixels)
                .expect("write macOS icon");
        }
        elements.extend(kind);
        elements.extend(((encoded.len() + 8) as u32).to_be_bytes());
        elements.extend(encoded);
    }
    let mut icon = b"icns".to_vec();
    icon.extend(((elements.len() + 8) as u32).to_be_bytes());
    icon.extend(elements);
    let path = std::path::Path::new("icons/icon.icns");
    if !std::fs::read(path).is_ok_and(|previous| previous == icon) {
        std::fs::write(path, icon).expect("write generated macOS ICNS");
    }
}

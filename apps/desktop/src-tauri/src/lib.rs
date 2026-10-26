//! Service layer is independently testable without GUI system dependencies.

#[cfg(test)]
mod capability_tests {
    #[test]
    fn manager_capability_is_local_to_main_on_all_supported_platforms() {
        let capability: serde_json::Value =
            serde_json::from_str(include_str!("../capabilities/main.json")).unwrap();
        assert_eq!(capability["windows"], serde_json::json!(["main"]));
        assert!(capability.get("remote").is_none());
        for platform in ["windows", "linux", "macOS"] {
            assert!(capability["platforms"]
                .as_array()
                .unwrap()
                .iter()
                .any(|value| value == platform));
        }
        for command in [
            "allow-preview",
            "allow-apply-preview",
            "allow-cancel-preview",
            "allow-preview-rollback",
        ] {
            assert!(capability["permissions"]
                .as_array()
                .unwrap()
                .iter()
                .any(|value| value == command));
        }
    }
}

#[cfg(test)]
mod macos_configuration_tests {
    #[test]
    fn macos_preview_uses_ephemeral_webview_without_a_publisher_identity() {
        let config: serde_json::Value =
            serde_json::from_str(include_str!("../tauri.macos.conf.json")).unwrap();
        assert_eq!(config["app"]["windows"][0]["label"], "main");
        assert_eq!(config["app"]["windows"][0]["incognito"], true);
        assert!(config["bundle"]["macOS"].get("signingIdentity").is_none());
    }
}

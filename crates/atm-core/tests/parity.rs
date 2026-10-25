use atm_core::{
    jsonc::{self, EditRequest},
    MASK,
};
use zeroize::Zeroizing;

fn rejected<T>(result: atm_core::Result<T>) -> atm_core::Error {
    match result {
        Ok(_) => panic!("expected the synthetic operation to be rejected"),
        Err(error) => error,
    }
}

fn request(pointer: &str) -> EditRequest {
    EditRequest {
        label: "假配置".into(),
        pointer: pointer.into(),
        secret: Zeroizing::new("FAKE_RUST_ONLY_NEW".into()),
        bearer: false,
        replace_variables: false,
    }
}
#[test]
fn comments_newlines_and_other_equal_values_are_untouched() {
    let input = b"{\r\n // FAKE_OLD\r\n \"key\" : \"FAKE_OLD\", /* keep */\r\n \"note\": \"FAKE_OLD\",\r\n}\r\n";
    let expected = b"{\r\n // FAKE_OLD\r\n \"key\" : \"FAKE_RUST_ONLY_NEW\", /* keep */\r\n \"note\": \"FAKE_OLD\",\r\n}\r\n";
    let edited = jsonc::edit(input, &[request("/key")]).expect("synthetic valid document");
    assert!(edited.bytes.as_slice() == expected);
    assert!(edited.fields[0].before == MASK && edited.fields[0].after == MASK);
    let preview = serde_json::to_string(&edited.fields).expect("safe view");
    assert!(!preview.contains("FAKE_OLD") && !preview.contains("FAKE_RUST_ONLY_NEW"));
}
#[test]
fn utf8_bom_utf16_le_be_and_unicode_are_preserved() {
    let source = "{\n // 中文\n \"key\":\"FAKE_OLD\", \"note\":\"😀\"\n}\n";
    let expected = "{\n // 中文\n \"key\":\"FAKE_RUST_ONLY_NEW\", \"note\":\"😀\"\n}\n";
    for big in [false, true] {
        let encode = |text: &str| {
            let mut bytes = if big {
                vec![0xfe, 0xff]
            } else {
                vec![0xff, 0xfe]
            };
            for unit in text.encode_utf16() {
                bytes.extend(if big {
                    unit.to_be_bytes()
                } else {
                    unit.to_le_bytes()
                });
            }
            bytes
        };
        let edited = jsonc::edit(&encode(source), &[request("/key")]).expect("valid UTF16");
        assert!(edited.bytes.as_slice() == encode(expected));
    }
    let mut original = vec![0xef, 0xbb, 0xbf];
    original.extend(source.as_bytes());
    let mut result = vec![0xef, 0xbb, 0xbf];
    result.extend(expected.as_bytes());
    assert!(
        jsonc::edit(&original, &[request("/key")])
            .expect("valid UTF8 BOM")
            .bytes
            .as_slice()
            == result
    );
}
#[test]
fn pointer_arrays_escaped_names_and_string_escaping() {
    let mut req = request("/a~1b/~0x/0");
    req.secret = Zeroizing::new("FAKE_\"_\\_中文_😀".into());
    let edited =
        jsonc::edit(br#"{"a/b":{"~x":["FAKE_OLD","untouched"]}}"#, &[req]).expect("valid pointer");
    let parsed = jsonc::parse_value(&edited.bytes).expect("result valid");
    assert!(parsed["a/b"]["~x"][0].as_str() == Some("FAKE_\"_\\_中文_😀"));
    assert!(jsonc::normalize("/bad~2").is_err());
    assert!(jsonc::edit(br#"{"a":["x"]}"#, &[request("/a/00")]).is_err());
}
#[test]
fn plain_and_escaped_string_bodies_preserve_json_semantics() {
    let source = r#"{"escaped":"caf\u00e9 \u4e2d\u6587 \ud83d\ude00","plain":"café 中文 😀","empty":"","special":"a\tb\n\"\\\/"}"#;
    let value = jsonc::parse_value(source.as_bytes()).expect("valid mixed document");
    let expected: serde_json::Value = serde_json::from_str(source).expect("JSON reference");
    assert_eq!(value, expected);
    assert_eq!(value["escaped"], value["plain"]);
    assert_eq!(value["plain"].as_str(), Some("café 中文 😀"));
    assert_eq!(value["empty"].as_str(), Some(""));
    assert_eq!(value["special"].as_str(), Some("a\tb\n\"\\/"));
    // The escape-free path must still reject every raw JSON control byte.
    for control in 0u8..0x20 {
        let mut input = br#"{"key":"a"#.to_vec();
        input.push(control);
        input.extend_from_slice(br#"b"}"#);
        assert!(jsonc::parse_value(&input).is_err());
    }
}
#[test]
fn variable_references_default_to_protected_and_need_explicit_override() {
    for value in [
        "${input:key}",
        "Bearer ${input:key}",
        "${env:KEY}",
        "$(KEY)",
        "{{KEY}}",
        "%KEY%",
    ] {
        let input = format!(
            "{{\"key\":{}}}",
            serde_json::to_string(value).expect("fixture")
        );
        let mut req = request("/key");
        assert!(
            jsonc::edit(input.as_bytes(), &[req])
                .expect("protected")
                .bytes
                .as_slice()
                == input.as_bytes()
        );
        req = request("/key");
        req.replace_variables = true;
        assert!(
            jsonc::edit(input.as_bytes(), &[req])
                .expect("explicit override")
                .bytes
                .as_slice()
                != input.as_bytes()
        );
    }
}
#[test]
fn bearer_prefix_is_optional_and_never_duplicated() {
    for key in ["FAKE_NEW", "Bearer FAKE_NEW", "bearer Bearer FAKE_NEW"] {
        assert!(
            jsonc::bearer_value(key, true)
                .expect("valid header")
                .as_str()
                == "Bearer FAKE_NEW"
        );
        assert!(jsonc::bearer_value(key, false).expect("bare mode").as_str() == key);
    }
    assert!(jsonc::bearer_value("Bearer ", true).is_err());
}
#[test]
fn duplicate_ambiguous_missing_and_nonstring_fields_are_rejected() {
    for input in [
        r#"{"key":"x","key":"y"}"#,
        r#"{"key":"x","\u006bey":"y"}"#,
        r#"{"key":"x","other":{"a":1,"a":2}}"#,
    ] {
        assert!(jsonc::edit(input.as_bytes(), &[request("/key")]).is_err());
    }
    assert!(jsonc::edit(br#"{"key":"x"}"#, &[request("/key"), request("/key")]).is_err());
    for input in [
        r#"{"key":null}"#,
        r#"{"key":42}"#,
        r#"{"key":true}"#,
        r#"{"key":[]}"#,
        r#"{"key":{}}"#,
        r#"{"other":"x"}"#,
    ] {
        assert!(jsonc::edit(input.as_bytes(), &[request("/key")]).is_err());
    }
}
#[test]
fn malformed_structure_encodings_and_depth_are_rejected() {
    for input in [
        "",
        "{",
        "null",
        r#"{"key":"x"}garbage"#,
        r#"{"key":"unterminated}"#,
        r#"{"key":"\q"}"#,
        r#"{"key":01}"#,
        r#"{"key":NaN}"#,
        r#"{"key":"x",,}"#,
        "{/* unterminated",
        "[1,,2]",
    ] {
        assert!(jsonc::edit(input.as_bytes(), &[request("/key")]).is_err());
    }
    assert!(jsonc::edit(&[0xc3, 0x28], &[request("/key")]).is_err());
    assert!(jsonc::edit(&[0xff, 0xfe, 0, 0], &[request("/key")]).is_err());
    let deep = format!("{}0{}", "[".repeat(70), "]".repeat(70));
    assert!(jsonc::parse_value(deep.as_bytes()).is_err());
}

#[cfg(windows)]
mod win {
    use super::*;
    use atm_core::{
        batch::{AtomicReplacer, BatchUpdater, Outcome},
        windows, Error, Result, TargetMapping, Vault,
    };
    use std::{fs, path::Path};
    use uuid::Uuid;

    pub(super) fn setup(root: &Path) -> (Vault, Uuid, String) {
        let mut vault = Vault::open(&root.join("vault")).expect("isolated vault");
        let key = vault
            .save_key(
                None,
                "测试密钥".into(),
                Zeroizing::new("FAKE_RUST_ONLY_NEW".into()),
            )
            .expect("add key");
        let path = root.join("synthetic.jsonc");
        fs::write(
            &path,
            b"{\r\n// keep\r\n\"key\":\"FAKE_OLD\",\"second\":\"FAKE_OTHER\",\r\n}\r\n",
        )
        .expect("fixture");
        (vault, key, path.to_string_lossy().into_owned())
    }
    pub(super) fn target(vault: &mut Vault, key: Uuid, path: &str, pointer: &str) -> Uuid {
        vault
            .save_target(TargetMapping {
                id: Uuid::nil(),
                label: "假配置".into(),
                file_path: path.into(),
                pointer: pointer.into(),
                key_id: key,
                bearer_prefix: false,
                replace_variables: false,
            })
            .expect("register target")
    }
    #[test]
    fn dpapi_current_user_roundtrip_tamper_and_ciphertext() {
        let bytes = b"FAKE_DPAPI_ONLY";
        let cipher = windows::crypt(bytes, true).expect("protect");
        assert!(
            windows::crypt(&cipher, false)
                .expect("unprotect")
                .as_slice()
                == bytes
        );
        assert!(!cipher.windows(bytes.len()).any(|window| window == bytes));
        let mut tampered = cipher.to_vec();
        let index = tampered.len() - 8;
        tampered[index] ^= 0x51;
        assert!(windows::crypt(&tampered, false).is_err());
    }
    #[test]
    fn vault_crud_mask_persistence_refs_duplicates_and_lock() {
        let dir = tempfile::tempdir().expect("isolated root");
        let (mut vault, key, path) = setup(dir.path());
        assert!(Vault::open(vault.directory()).is_err());
        assert!(vault
            .save_key(None, "测试密钥".into(), Zeroizing::new("FAKE_OTHER".into()))
            .is_err());
        assert!(vault
            .save_key(None, "bad".into(), Zeroizing::new(" FAKE ".into()))
            .is_err());
        vault
            .save_key(Some(key), "重命名".into(), Zeroizing::new(String::new()))
            .expect("retain key");
        let id = target(&mut vault, key, &path, "/key");
        assert!(vault.delete_key(key).is_err());
        assert!(vault
            .save_target(TargetMapping {
                id: Uuid::nil(),
                label: "same".into(),
                file_path: path.to_uppercase(),
                pointer: "/key".into(),
                key_id: key,
                bearer_prefix: false,
                replace_variables: false
            })
            .is_err());
        let safe = serde_json::to_string(&vault.snapshot()).expect("safe view");
        assert!(!safe.contains("FAKE_RUST_ONLY_NEW"));
        let store = vault.directory().to_owned();
        drop(vault);
        let mut reopened = Vault::open(&store).expect("reopen");
        assert!(reopened.snapshot().keys[0].name == "重命名");
        reopened.delete_target(id).expect("delete mapping");
        reopened.delete_key(key).expect("delete key");
    }
    #[test]
    fn grouped_batch_backups_noop_cancel_and_whole_file_rollback() {
        let dir = tempfile::tempdir().expect("isolated root");
        let (mut vault, key, path) = setup(dir.path());
        let original = fs::read(&path).expect("original");
        let a = target(&mut vault, key, &path, "/key");
        let b = target(&mut vault, key, &path, "/second");
        let updater = BatchUpdater::new(vault.backup_directory());
        let mut plan = updater.preview(&vault, &[a, b]);
        assert!(plan.view().files.len() == 1);
        assert!(updater.apply(&mut plan, Uuid::new_v4(), true).is_err());
        let id = plan.id;
        assert!(updater.apply(&mut plan, id, false).is_err());
        let results = updater.apply(&mut plan, id, true).expect("apply");
        assert!(results[0].outcome == Outcome::Applied);
        assert!(updater.apply(&mut plan, id, true).is_err());
        let backups = updater.backups().expect("backups");
        assert!(backups.len() == 1);
        let backup_bytes = fs::read(&backups[0].backup_path).expect("cipher backup");
        assert!(!backup_bytes.windows(10).any(|b| b == b"FAKE_OTHER"));
        let mut rollback = updater
            .preview_rollback(&backups[0].backup_path)
            .expect("rollback preview");
        let id = rollback.id;
        assert!(
            updater.apply(&mut rollback, id, true).expect("restore")[0].outcome == Outcome::Applied
        );
        assert!(fs::read(&path).expect("restored") == original);
        assert!(updater.backups().expect("restore backup").len() == 2);
        let mut cancelled = updater.preview(&vault, &[a]);
        let id = cancelled.id;
        cancelled.cancel();
        assert!(updater.apply(&mut cancelled, id, true).is_err());
    }
    #[test]
    fn stale_content_time_identity_and_rollback_conflicts() {
        let dir = tempfile::tempdir().expect("isolated root");
        let (mut vault, key, path) = setup(dir.path());
        let id = target(&mut vault, key, &path, "/key");
        let updater = BatchUpdater::new(vault.backup_directory());
        let mut plan = updater.preview(&vault, &[id]);
        fs::write(&path, b"{\"key\":\"FAKE_XXX\"}").expect("later edit");
        let plan_id = plan.id;
        assert!(
            updater.apply(&mut plan, plan_id, true).expect("conflict")[0].outcome
                == Outcome::Conflict
        );
        let mut plan = updater.preview(&vault, &[id]);
        let plan_id = plan.id;
        let applied = updater
            .apply(&mut plan, plan_id, true)
            .expect("fresh apply");
        let mut rollback = updater
            .preview_rollback(applied[0].backup_path.as_ref().expect("backup"))
            .expect("rollback before edit");
        fs::write(&path, b"{\"key\":\"FAKE_LATER_EDIT\"}").expect("after rollback preview");
        let rollback_id = rollback.id;
        assert!(
            updater
                .apply(&mut rollback, rollback_id, true)
                .expect("conflict")[0]
                .outcome
                == Outcome::Conflict
        );
        assert!(updater
            .preview_rollback(applied[0].backup_path.as_ref().expect("backup"))
            .is_err());
        let mut plan = updater.preview(&vault, &[id]);
        fs::remove_file(&path).expect("remove own fixture");
        let plan_id = plan.id;
        assert!(
            updater.apply(&mut plan, plan_id, true).expect("missing")[0].outcome
                == Outcome::Conflict
        );
    }
    struct FailBefore;
    impl AtomicReplacer for FailBefore {
        fn replace(&self, _: &Path, _: &Path) -> Result<()> {
            Err(Error::new("INJECTED", "合成替换失败。"))
        }
    }
    #[test]
    fn replacement_failure_preserves_original_and_retains_encrypted_backup() {
        let dir = tempfile::tempdir().expect("isolated root");
        let (mut vault, key, path) = setup(dir.path());
        let original = fs::read(&path).expect("fixture");
        let id = target(&mut vault, key, &path, "/key");
        let updater = BatchUpdater::with_replacer(vault.backup_directory(), Box::new(FailBefore));
        let mut plan = updater.preview(&vault, &[id]);
        let plan_id = plan.id;
        let results = updater
            .apply(&mut plan, plan_id, true)
            .expect("partial results");
        assert!(results[0].outcome == Outcome::Failed && results[0].backup_path.is_some());
        assert!(fs::read(&path).expect("unchanged") == original);
        assert!(
            !fs::read_dir(dir.path()).expect("own dir").any(|entry| entry
                .expect("entry")
                .file_name()
                .to_string_lossy()
                .starts_with(".atm-"))
        );
    }
}

#[test]
fn unsorted_multiple_patches_preserve_every_unrelated_byte_in_all_encodings() {
    let input = "/*prefix😀*/{\r\n\t\"first\":\"OLD_A\",\n\"unchanged\":\"\\u4e2d\\/\\uD83D\\uDE00\",\r\"last\":\"OLD_B\",}\n// suffix";
    let expected = input
        .replace("\"OLD_A\"", "\"FAKE_RUST_ONLY_NEW\"")
        .replace("\"OLD_B\"", "\"FAKE_RUST_ONLY_NEW\"");
    for encoding in 0..4 {
        let encode = |text: &str| -> Vec<u8> {
            match encoding {
                0 => text.as_bytes().to_vec(),
                1 => [vec![0xef, 0xbb, 0xbf], text.as_bytes().to_vec()].concat(),
                2 => [
                    vec![0xff, 0xfe],
                    text.encode_utf16().flat_map(u16::to_le_bytes).collect(),
                ]
                .concat(),
                _ => [
                    vec![0xfe, 0xff],
                    text.encode_utf16().flat_map(u16::to_be_bytes).collect(),
                ]
                .concat(),
            }
        };
        let output = jsonc::edit(&encode(input), &[request("/last"), request("/first")])
            .expect("exact spans");
        assert_eq!(output.bytes.as_slice(), encode(&expected));
        assert_eq!(output.fields[0].pointer, "/last");
    }
}

#[test]
fn semantically_equal_values_keep_their_original_escape_spelling() {
    let input = br#"{ "key" : "FAKE_\u0052UST_ONLY_NEW", "other": "\u0061" }"#;
    let result = jsonc::edit(input, &[request("/key")]).expect("no-op");
    assert_eq!(result.bytes.as_slice(), input);
    assert_eq!(result.fields[0].status, "无需修改");
    assert_eq!(
        jsonc::edit(input, &[])
            .expect("empty selection")
            .bytes
            .as_slice(),
        input
    );
}

#[test]
fn pointers_resolve_empty_properties_case_sensitively_and_decode_once() {
    let input = br#"{"":"x","~1":"y","a/b":"z","Key":"keep"}"#;
    for pointer in ["/", "/~01", "/a~1b"] {
        assert!(jsonc::edit(input, &[request(pointer)]).is_ok());
    }
    for pointer in ["/key", "/~1", "#", "key", "/~", "/~3"] {
        assert!(jsonc::edit(input, &[request(pointer)]).is_err());
    }
    assert_eq!(
        jsonc::normalize("/a~1b/~01//~0").expect("normalized"),
        "/a~1b/~01//~0"
    );
    assert_eq!(
        rejected(jsonc::edit(input, &[request("")])).code,
        "FIELD_TYPE"
    );
    let array = br#"["x", {"0":"y"}]"#;
    assert!(jsonc::edit(array, &[request("/0")]).is_ok());
    assert!(jsonc::edit(array, &[request("/1/0")]).is_ok());
    for pointer in [
        "/-",
        "/-1",
        "/+0",
        "/00",
        "/ 0",
        "/0 ",
        "/18446744073709551616",
    ] {
        assert!(jsonc::edit(array, &[request(pointer)]).is_err());
    }
}

#[test]
fn comment_markers_inside_strings_and_adjacent_scalar_comments_are_legal() {
    let input = br#"{/*a*/"key":"http://example.invalid/*text*/", "n":1/*b*/, "b":true//c
,"z":null, "array":[false,],}"#;
    let result = jsonc::edit(input, &[request("/key")]).expect("JSONC tokens");
    assert!(String::from_utf8_lossy(&result.bytes).contains("1/*b*/"));
    assert!(String::from_utf8_lossy(&result.bytes).contains("true//c\n"));
    assert_eq!(
        jsonc::parse_value(&result.bytes).expect("parse")["array"][0],
        false
    );
}

#[test]
fn numeric_spelling_and_precision_are_untouched() {
    let input = br#"{"key":"x","large":123456789012345678901234567890,"exp":-1.25000E+300,"zero":-0,"small":1e-999}"#;
    let output = jsonc::edit(input, &[request("/key")]).expect("large numbers");
    let suffix = b",\"large\":123456789012345678901234567890,\"exp\":-1.25000E+300,\"zero\":-0,\"small\":1e-999}";
    assert!(output.bytes.ends_with(suffix));
}

#[test]
fn malformed_unicode_and_scalar_tokens_are_rejected_without_input_in_errors() {
    for input in [
        r#"{"key":"\uD800"}"#,
        r#"{"key":"\uDC00"}"#,
        r#"{"key":"\uD800\u0041"}"#,
        r#"{"key":"\uZZZZ"}"#,
        r#"{"key":+1}"#,
        r#"{"key":1.}"#,
        r#"{"key":.1}"#,
        r#"{"key":1e}"#,
        r#"{"key":Infinity}"#,
        r#"{"key":undefined}"#,
        r#"{"FAKE_DO_NOT_LOG":"x"}FAKE_DO_NOT_LOG"#,
    ] {
        let error = rejected(jsonc::edit(input.as_bytes(), &[request("/key")]));
        let visible = serde_json::to_string(&error).expect("safe error");
        assert!(!visible.contains("FAKE_DO_NOT_LOG"));
    }
    for bytes in [
        vec![0xff, 0xfe, b'{'],
        vec![0xff, 0xfe, 0, 0xd8],
        vec![0xfe, 0xff, 0xdc, 0],
        vec![0xef, 0xbb, 0xbf, 0xff],
    ] {
        assert_eq!(rejected(jsonc::edit(&bytes, &[])).code, "ENCODING_INVALID");
    }
}

#[test]
fn variable_headers_are_preserved_and_previews_never_expose_variable_names() {
    for value in [
        "Bearer %FAKE_PRIVATE_ENV%",
        "prefix-%FAKE_PRIVATE_ENV%-suffix",
        "%CUSTOM.NAME%",
    ] {
        let input = format!(
            "{{\"key\":{}}}",
            serde_json::to_string(value).expect("fixture")
        );
        let mut req = request("/key");
        req.bearer = true;
        req.secret = Zeroizing::new("Bearer ".into());
        let result =
            jsonc::edit(input.as_bytes(), &[req]).expect("preserve before computing replacement");
        assert_eq!(result.bytes.as_slice(), input.as_bytes());
        let view = serde_json::to_string(&result.fields).expect("view");
        assert!(!view.contains("FAKE_PRIVATE_ENV") && !view.contains("CUSTOM.NAME"));
    }
    for value in ["100% ready", "50%", "percent%tail", "a%%b"] {
        assert!(!jsonc::has_variable(value));
    }
    let mut req = request("/key");
    req.bearer = true;
    let result = jsonc::edit(br#"{"key":"Bearer FAKE_OLD"}"#, &[req]).expect("header");
    assert_eq!(result.fields[0].before, format!("Bearer {MASK}"));
    assert_eq!(result.fields[0].after, format!("Bearer {MASK}"));
}

#[test]
fn depth_node_count_input_and_output_bounds_are_enforced() {
    let allowed = format!("{}0{}", "[".repeat(64), "]".repeat(64));
    assert!(jsonc::parse_value(allowed.as_bytes()).is_ok());
    let excessive = format!("{}0{}", "[".repeat(66), "]".repeat(66));
    assert_eq!(
        rejected(jsonc::parse_value(excessive.as_bytes())).code,
        "JSON_LIMIT"
    );
    let nodes = format!("[{}0]", "0,".repeat(100000));
    assert_eq!(
        rejected(jsonc::parse_value(nodes.as_bytes())).code,
        "JSON_LIMIT"
    );
    let oversized = vec![b' '; atm_core::MAX_CONFIG_BYTES + 1];
    assert_eq!(rejected(jsonc::edit(&oversized, &[])).code, "CONFIG_SIZE");
    let mut full = br#"{"key":"x"}"#.to_vec();
    full.resize(atm_core::MAX_CONFIG_BYTES, b' ');
    assert_eq!(
        rejected(jsonc::edit(&full, &[request("/key")])).code,
        "CONFIG_SIZE"
    );
    let requests: Vec<_> = (0..501).map(|_| request("/key")).collect();
    assert_eq!(
        rejected(jsonc::edit(br#"{"key":"x"}"#, &requests)).code,
        "TARGET_LIMIT"
    );
}

#[test]
fn io_error_text_never_propagates_original_exception_details() {
    let error = atm_core::Error::io(std::io::Error::other("FAKE_SECRET_ERROR"));
    assert!(!error.to_string().contains("FAKE_SECRET_ERROR"));
    assert!(!serde_json::to_string(&error)
        .expect("safe JSON")
        .contains("FAKE_SECRET_ERROR"));
}

#[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
#[test]
fn secure_windows_operations_fail_closed_on_other_platforms() {
    use atm_core::windows;
    assert_eq!(
        rejected(windows::crypt(b"FAKE", true)).code,
        "WINDOWS_REQUIRED"
    );
    assert_eq!(
        rejected(windows::canonical("C:\\fixture.json")).code,
        "WINDOWS_REQUIRED"
    );
    assert_eq!(
        windows::hash(b"abc"),
        "BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD"
    );
}

#[cfg(windows)]
mod failure_paths {
    use super::win::{setup, target};
    use atm_core::{
        batch::{AtomicReplacer, BatchUpdater, FileResult, Outcome, Preview},
        jsonc, windows, Error, Result, Vault,
    };
    use std::{
        fs::{self, File, OpenOptions},
        os::windows::fs::OpenOptionsExt,
        path::Path,
        sync::{Arc, Mutex},
        time::{Duration, SystemTime},
    };
    use uuid::Uuid;
    use zeroize::Zeroizing;

    type Replacement = dyn Fn(&Path, &Path) -> Result<()> + Send + Sync;
    struct Injected(Box<Replacement>);
    impl AtomicReplacer for Injected {
        fn replace(&self, temp: &Path, destination: &Path) -> Result<()> {
            (self.0)(temp, destination)
        }
    }
    fn apply(updater: &BatchUpdater, plan: &mut Preview) -> Vec<FileResult> {
        let id = plan.id;
        updater.apply(plan, id, true).expect("per-file result")
    }
    fn safe_failure() -> Error {
        Error::io(std::io::Error::other("FAKE_SECRET_EXCEPTION"))
    }
    fn no_temporary(root: &Path) {
        assert!(!fs::read_dir(root).expect("test root").any(|entry| entry
            .expect("entry")
            .file_name()
            .to_string_lossy()
            .starts_with(".atm-")));
    }

    #[test]
    fn invalid_field_rejects_entire_file_but_independent_file_succeeds() {
        let dir = tempfile::tempdir().expect("root");
        let (mut vault, key, path) = setup(dir.path());
        let original = fs::read(&path).expect("original");
        let valid = target(&mut vault, key, &path, "/key");
        let invalid = target(&mut vault, key, &path, "/missing");
        let independent = dir.path().join("independent.json");
        fs::write(&independent, br#"{"key":"FAKE_OTHER"}"#).expect("fixture");
        let other = target(&mut vault, key, independent.to_str().expect("path"), "/key");
        let updater = BatchUpdater::new(vault.backup_directory());
        let mut plan = updater.preview(&vault, &[valid, invalid, other]);
        assert_eq!(plan.view().files.len(), 2);
        let results = apply(&updater, &mut plan);
        assert_eq!(
            results
                .iter()
                .filter(|r| r.outcome == Outcome::Failed)
                .count(),
            1
        );
        assert_eq!(
            results
                .iter()
                .filter(|r| r.outcome == Outcome::Applied)
                .count(),
            1
        );
        assert_eq!(fs::read(&path).expect("unchanged"), original);
        assert_eq!(updater.backups().expect("backups").len(), 1);
    }

    #[test]
    fn validator_is_called_once_per_file_and_failure_never_creates_backup() {
        let dir = tempfile::tempdir().expect("root");
        let (mut vault, key, path) = setup(dir.path());
        let original = fs::read(&path).expect("original");
        let expected_path = windows::canonical(&path).expect("canonical fixture path");
        let a = target(&mut vault, key, &path, "/key");
        let b = target(&mut vault, key, &path, "/second");
        let updater = BatchUpdater::new(vault.backup_directory());
        let calls = std::cell::Cell::new(0usize);
        let mut plan =
            updater.preview_with_validator(&vault, &[a, b], |canonical, bytes, requests| {
                calls.set(calls.get() + 1);
                assert!(windows::equal_case(canonical, &expected_path));
                assert_eq!(bytes, original.as_slice());
                assert_eq!(requests.len(), 2);
                Err(Error::new("SYNTHETIC_SCHEMA", "合成模板验证失败。"))
            });
        assert_eq!(calls.get(), 1);
        assert_eq!(apply(&updater, &mut plan)[0].outcome, Outcome::Failed);
        assert_eq!(fs::read(&path).expect("unchanged"), original);
        assert!(updater.backups().expect("backups").is_empty());
    }

    #[test]
    fn malformed_file_duplicate_selection_and_unknown_target_are_safe_failures() {
        let dir = tempfile::tempdir().expect("root");
        let (mut vault, key, path) = setup(dir.path());
        let target_id = target(&mut vault, key, &path, "/key");
        let updater = BatchUpdater::new(vault.backup_directory());
        let mut duplicate = updater.preview(&vault, &[target_id, target_id]);
        assert_eq!(
            apply(&updater, &mut duplicate)[0].code,
            Some("FIELD_AMBIGUOUS")
        );
        let mut unknown = updater.preview(&vault, &[Uuid::new_v4()]);
        assert_eq!(
            apply(&updater, &mut unknown)[0].code,
            Some("TARGET_MISSING")
        );
        fs::write(&path, br#"{"key":"FAKE_SECRET_MALFORMED""#).expect("malformed fixture");
        let mut malformed = updater.preview(&vault, &[target_id]);
        let view = serde_json::to_string(&malformed.view()).expect("preview");
        assert!(!view.contains("FAKE_SECRET_MALFORMED"));
        assert_eq!(apply(&updater, &mut malformed)[0].outcome, Outcome::Failed);
        assert!(updater.backups().expect("backups").is_empty());
    }

    #[test]
    fn successful_noop_and_protected_noop_make_no_backup_but_stale_noop_conflicts() {
        let dir = tempfile::tempdir().expect("root");
        let (mut vault, key, path) = setup(dir.path());
        let id = target(&mut vault, key, &path, "/key");
        let updater = BatchUpdater::new(vault.backup_directory());
        for input in [
            br#"{"key":"FAKE_RUST_ONLY_NEW"}"#.as_slice(),
            br#"{"key":"${input:FAKE_VARIABLE}"}"#.as_slice(),
        ] {
            fs::write(&path, input).expect("fixture");
            let mut plan = updater.preview(&vault, &[id]);
            assert!(!plan.view().files[0].changed);
            assert_eq!(apply(&updater, &mut plan)[0].outcome, Outcome::Skipped);
            let mut stale = updater.preview(&vault, &[id]);
            fs::write(&path, [input, b"\n// later"].concat()).expect("later edit");
            assert_eq!(apply(&updater, &mut stale)[0].outcome, Outcome::Conflict);
        }
        assert!(updater.backups().expect("backups").is_empty());
    }

    #[test]
    fn only_timestamp_or_identity_changes_are_conflicts() {
        let dir = tempfile::tempdir().expect("root");
        let (mut vault, key, path) = setup(dir.path());
        let id = target(&mut vault, key, &path, "/key");
        let updater = BatchUpdater::new(vault.backup_directory());
        let mut timed = updater.preview(&vault, &[id]);
        File::options()
            .write(true)
            .open(&path)
            .expect("timestamp handle")
            .set_times(
                fs::FileTimes::new().set_modified(SystemTime::now() + Duration::from_secs(300)),
            )
            .expect("change timestamp");
        assert_eq!(apply(&updater, &mut timed)[0].outcome, Outcome::Conflict);
        let mut identity = updater.preview(&vault, &[id]);
        let replacement = dir.path().join("identity-replacement.json");
        fs::write(&replacement, fs::read(&path).expect("bytes")).expect("replacement");
        windows::replace(&replacement, Path::new(&path)).expect("replace equal bytes");
        assert_eq!(apply(&updater, &mut identity)[0].outcome, Outcome::Conflict);
        assert!(updater.backups().expect("backups").is_empty());
    }

    #[test]
    fn partial_replacement_failure_keeps_other_success_and_original_failed_file() {
        let dir = tempfile::tempdir().expect("root");
        let (mut vault, key, path) = setup(dir.path());
        let other = dir.path().join("fail.json");
        let bytes = br#"{"key":"FAKE_UNCHANGED"}"#;
        fs::write(&other, bytes).expect("fixture");
        let a = target(&mut vault, key, &path, "/key");
        let b = target(&mut vault, key, other.to_str().expect("path"), "/key");
        let updater = BatchUpdater::with_replacer(
            vault.backup_directory(),
            Box::new(Injected(Box::new(|temp, dest| {
                if dest.file_name().and_then(|v| v.to_str()) == Some("fail.json") {
                    Err(safe_failure())
                } else {
                    windows::replace(temp, dest)
                }
            }))),
        );
        let mut plan = updater.preview(&vault, &[a, b]);
        let result = apply(&updater, &mut plan);
        assert_eq!(result[0].outcome, Outcome::Applied);
        assert_eq!(result[1].outcome, Outcome::Failed);
        assert!(result[1].backup_path.is_some());
        assert_eq!(fs::read(&other).expect("failed bytes"), bytes);
        assert!(!serde_json::to_string(&result)
            .expect("safe results")
            .contains("FAKE_SECRET_EXCEPTION"));
        no_temporary(dir.path());
    }

    #[test]
    fn replace_then_error_or_later_write_reports_exact_uncertainty() {
        for behavior in 0..4 {
            let dir = tempfile::tempdir().expect("root");
            let (mut vault, key, path) = setup(dir.path());
            let id = target(&mut vault, key, &path, "/key");
            let updater = BatchUpdater::with_replacer(
                vault.backup_directory(),
                Box::new(Injected(Box::new(move |temp, dest| {
                    windows::replace(temp, dest)?;
                    match behavior {
                        0 => Err(safe_failure()),
                        1 => {
                            fs::write(dest, br#"{"key":"FAKE_APPLICATION_UPDATE"}"#)?;
                            Ok(())
                        }
                        2 => {
                            fs::write(dest, br#"{"key":"FAKE_APPLICATION_UPDATE"}"#)?;
                            Err(safe_failure())
                        }
                        _ => {
                            fs::remove_file(dest)?;
                            Err(safe_failure())
                        }
                    }
                }))),
            );
            let mut plan = updater.preview(&vault, &[id]);
            let result = apply(&updater, &mut plan);
            assert_eq!(
                result[0].outcome,
                if behavior < 2 {
                    Outcome::AppliedUnverified
                } else {
                    Outcome::OutcomeUnknown
                }
            );
            if behavior == 1 {
                assert_eq!(result[0].code, Some("POST_WRITE_CHANGED"));
            }
            assert!(result[0].backup_path.is_some());
            no_temporary(dir.path());
        }
    }

    #[test]
    fn backup_creation_failure_prevents_plaintext_staging_and_target_write() {
        let dir = tempfile::tempdir().expect("root");
        let (mut vault, key, path) = setup(dir.path());
        let original = fs::read(&path).expect("original");
        let id = target(&mut vault, key, &path, "/key");
        let blocked = dir.path().join("not-a-directory");
        fs::write(&blocked, b"test").expect("block backup path");
        let updater = BatchUpdater::new(blocked);
        let mut plan = updater.preview(&vault, &[id]);
        let result = apply(&updater, &mut plan);
        assert_eq!(result[0].outcome, Outcome::Failed);
        assert!(result[0].backup_path.is_none());
        assert_eq!(fs::read(&path).expect("unchanged"), original);
        no_temporary(dir.path());
    }

    #[test]
    fn plaintext_staging_cleanup_failure_is_explicit_and_recoverable() {
        let dir = tempfile::tempdir().expect("root");
        let (mut vault, key, path) = setup(dir.path());
        let id = target(&mut vault, key, &path, "/key");
        let held: Arc<Mutex<Option<File>>> = Arc::new(Mutex::new(None));
        let capture = Arc::clone(&held);
        let updater = BatchUpdater::with_replacer(
            vault.backup_directory(),
            Box::new(Injected(Box::new(move |temp, _| {
                *capture.lock().expect("test lock") =
                    Some(OpenOptions::new().read(true).share_mode(1).open(temp)?);
                Err(safe_failure())
            }))),
        );
        let mut plan = updater.preview(&vault, &[id]);
        let result = apply(&updater, &mut plan);
        assert_eq!(result[0].outcome, Outcome::Failed);
        let temporary = result[0]
            .temporary_path
            .as_ref()
            .expect("reported cleartext residue");
        assert!(result[0].message.contains("明文暂存"));
        assert!(Path::new(temporary).exists());
        held.lock().expect("test lock").take();
        fs::remove_file(temporary).expect("clean test residue");
        no_temporary(dir.path());
    }

    #[test]
    fn readonly_and_exclusively_held_files_fail_without_changes() {
        struct RestoreReadOnly {
            path: String,
            permissions: fs::Permissions,
        }
        impl Drop for RestoreReadOnly {
            fn drop(&mut self) {
                let _ = fs::set_permissions(&self.path, self.permissions.clone());
            }
        }
        for readonly in [false, true] {
            let dir = tempfile::tempdir().expect("root");
            let (mut vault, key, path) = setup(dir.path());
            let id = target(&mut vault, key, &path, "/key");
            let original = fs::read(&path).expect("original");
            let updater = BatchUpdater::new(vault.backup_directory());
            let mut plan = updater.preview(&vault, &[id]);
            let original_permissions = fs::metadata(&path).expect("metadata").permissions();
            let restore = readonly.then(|| RestoreReadOnly {
                path: path.clone(),
                permissions: original_permissions.clone(),
            });
            let held = if readonly {
                let mut permissions = original_permissions;
                permissions.set_readonly(true);
                fs::set_permissions(&path, permissions).expect("read-only");
                None
            } else {
                Some(
                    OpenOptions::new()
                        .read(true)
                        .write(true)
                        .share_mode(0)
                        .open(&path)
                        .expect("exclusive test handle"),
                )
            };
            let result = apply(&updater, &mut plan);
            drop(held);
            drop(restore);
            assert_eq!(result[0].outcome, Outcome::Failed);
            assert_eq!(fs::read(&path).expect("unchanged"), original);
            no_temporary(dir.path());
        }
    }

    #[test]
    fn corrupt_vault_or_invalid_version_is_never_overwritten() {
        for bytes in [
            vec![1, 2, 3, 4],
            windows::crypt(br#"{"Version":2,"Keys":[],"Targets":[]}"#, true)
                .expect("encrypted fixture")
                .to_vec(),
        ] {
            let dir = tempfile::tempdir().expect("root");
            let path = dir.path().join("vault.dpapi");
            fs::write(&path, &bytes).expect("fixture");
            assert!(Vault::open(dir.path()).is_err());
            assert_eq!(fs::read(&path).expect("retained"), bytes);
        }
    }

    #[test]
    fn failed_vault_commit_keeps_memory_and_persisted_previous_document() {
        let dir = tempfile::tempdir().expect("root");
        let (mut vault, _, _) = setup(dir.path());
        let before = serde_json::to_vec(&vault.snapshot()).expect("safe snapshot");
        let store = vault.directory().join("vault.dpapi");
        let disk = fs::read(&store).expect("disk");
        let held = OpenOptions::new()
            .read(true)
            .share_mode(1)
            .open(&store)
            .expect("prevent replace");
        assert!(vault
            .save_key(
                None,
                "合成失败提交".into(),
                Zeroizing::new("FAKE_NEW_UNCOMMITTED".into())
            )
            .is_err());
        drop(held);
        assert_eq!(
            serde_json::to_vec(&vault.snapshot()).expect("safe snapshot"),
            before
        );
        assert_eq!(fs::read(&store).expect("disk unchanged"), disk);
        no_temporary(vault.directory());
    }

    #[test]
    fn deleted_old_target_does_not_block_registering_another_file() {
        let dir = tempfile::tempdir().expect("root");
        let (mut vault, key, path) = setup(dir.path());
        target(&mut vault, key, &path, "/key");
        fs::remove_file(&path).expect("delete fixture");
        let fresh = dir.path().join("fresh.json");
        fs::write(&fresh, br#"{"key":"FAKE_NEW"}"#).expect("fixture");
        target(&mut vault, key, fresh.to_str().expect("path"), "/key");
        assert_eq!(vault.snapshot().targets.len(), 2);
    }

    #[test]
    fn own_backup_scope_tamper_and_repeated_rollback_are_enforced() {
        let dir = tempfile::tempdir().expect("root");
        let (mut vault, key, path) = setup(dir.path());
        let original = fs::read(&path).expect("original");
        let id = target(&mut vault, key, &path, "/key");
        let updater = BatchUpdater::new(vault.backup_directory());
        let mut plan = updater.preview(&vault, &[id]);
        let result = apply(&updater, &mut plan);
        let backup = result[0].backup_path.as_ref().expect("backup");
        let outside = dir.path().join("outside.atmbackup");
        fs::copy(backup, &outside).expect("fixture copy");
        assert_eq!(
            super::rejected(updater.preview_rollback(outside.to_str().expect("path"))).code,
            "BACKUP_SCOPE"
        );
        let mut restore = updater.preview_rollback(backup).expect("restore");
        assert_eq!(apply(&updater, &mut restore)[0].outcome, Outcome::Applied);
        assert_eq!(fs::read(&path).expect("restored"), original);
        let mut repeat = updater.preview_rollback(backup).expect("repeated preview");
        assert_eq!(apply(&updater, &mut repeat)[0].outcome, Outcome::Skipped);
        assert_eq!(updater.backups().expect("backups").len(), 2);
        let mut corrupted = fs::read(backup).expect("ciphertext");
        let last = corrupted.len() - 8;
        corrupted[last] ^= 0x51;
        fs::write(backup, corrupted).expect("synthetic tamper");
        assert!(updater.preview_rollback(backup).is_err());
        assert_eq!(
            updater
                .backups()
                .expect("enumerate even bad backup")
                .iter()
                .filter(|b| b.error.is_some())
                .count(),
            1
        );
        assert_eq!(fs::read(&path).expect("unchanged"), original);
    }

    #[test]
    fn local_path_rejects_devices_network_streams_and_hardlinks() {
        for path in [
            "relative.json",
            "\\\\server\\share\\test.json",
            "\\\\?\\C:\\test.json",
            "C:\\test.json:stream",
            "C:\\NUL.json",
            "C:\\CON",
            "C:\\test.json.",
        ] {
            assert!(windows::canonical(path).is_err());
        }
        let dir = tempfile::tempdir().expect("root");
        let path = dir.path().join("original.json");
        fs::write(&path, br#"{"key":"FAKE"}"#).expect("fixture");
        let alias = dir.path().join("alias.json");
        fs::hard_link(&path, &alias).expect("local hardlink fixture");
        assert_eq!(
            super::rejected(windows::canonical(path.to_str().expect("path"))).code,
            "PATH_HARDLINK"
        );
        fs::remove_file(alias).expect("remove alias");
        assert!(windows::read_snapshot(path.to_str().expect("path")).is_ok());
        let toml = dir.path().join("config.TOML");
        fs::write(&toml, b"key='FAKE'").expect("TOML fixture");
        assert_eq!(
            super::rejected(windows::canonical(toml.to_str().expect("path"))).code,
            "TOML_UNSUPPORTED"
        );
    }

    #[test]
    fn snapshot_hash_and_fingerprint_cover_original_encoded_bytes() {
        let dir = tempfile::tempdir().expect("root");
        let path = dir.path().join("utf16.json");
        let text = "{\"key\":\"FAKE\",\"note\":\"😀\"}\r\n";
        let bytes = [
            vec![0xff, 0xfe],
            text.encode_utf16().flat_map(u16::to_le_bytes).collect(),
        ]
        .concat();
        fs::write(&path, &bytes).expect("fixture");
        let snapshot = windows::read_snapshot(path.to_str().expect("path")).expect("snapshot");
        assert_eq!(snapshot.bytes.as_slice(), bytes);
        assert_eq!(snapshot.fingerprint.hash, windows::hash(&bytes));
        assert_eq!(snapshot.fingerprint.length, bytes.len() as u64);
        assert!(!snapshot.fingerprint.identity.is_empty());
        assert!(snapshot.fingerprint.last_write > 0);
        assert_eq!(
            jsonc::parse_value(&snapshot.bytes).expect("UTF16 parse")["note"],
            "😀"
        );
    }
}

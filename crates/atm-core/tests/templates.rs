//! Synthetic-only template tests. No real key, application config, or file I/O.
use atm_core::{
    jsonc::{self, EditRequest},
    templates::{
        self, ApplicationIdentity, FieldBinding, PatchDefaults, SchemaSource, SchemaSourceKind,
        Template, SCHEMA_DIALECT,
    },
    Result,
};
use serde_json::{json, Value};
use uuid::Uuid;
use zeroize::Zeroizing;

fn identity() -> ApplicationIdentity {
    ApplicationIdentity {
        id: "synthetic-app".into(),
        display_name: "Synthetic test application".into(),
        config_file_names: vec!["synthetic.jsonc".into()],
    }
}

fn template(mut schema: Value) -> Template {
    schema
        .as_object_mut()
        .unwrap()
        .insert("$schema".into(), json!(SCHEMA_DIALECT));
    Template {
        format_version: 1,
        id: Uuid::new_v4(),
        name: "Synthetic structure".into(),
        application: identity(),
        source: SchemaSource {
            kind: SchemaSourceKind::UserAuthored,
            version: "test-v1".into(),
            confirmed: true,
        },
        bindings: vec![FieldBinding {
            name: "key".into(),
            pointer: "/key".into(),
        }],
        write_allowlist: vec!["/key".into()],
        defaults: PatchDefaults::default(),
        schema,
    }
}

fn edit(pointer: &str, secret: &str) -> EditRequest {
    EditRequest {
        label: "Synthetic binding".into(),
        pointer: pointer.into(),
        secret: Zeroizing::new(secret.into()),
        bearer: false,
        replace_variables: false,
    }
}

fn code<T>(result: Result<T>) -> &'static str {
    match result {
        Ok(_) => panic!("Expected operation to fail"),
        Err(error) => error.code,
    }
}

#[test]
fn inference_preserves_types_and_string_candidates_but_never_sample_values() {
    let sample = br#"{
        "key":"SYNTHETIC-DO-NOT-PERSIST", "enabled":true, "attempts":3,
        "ratio":0.25, "unset":null, "empty":[],
        "nested":{"token":"SYNTHETIC-NESTED"},
        "array":["SYNTHETIC-ARRAY", 1, false, {"secret":"SYNTHETIC-CHILD"}]
    }"#;
    let candidate = templates::infer_candidate(sample, identity(), "Candidate".into()).unwrap();
    assert!(candidate.requires_confirmation);
    assert!(!candidate.template.source.confirmed);
    assert_eq!(
        candidate.template.source.kind,
        SchemaSourceKind::SampleInferred
    );
    assert!(candidate.template.write_allowlist.is_empty());
    let encoded = serde_json::to_string(&candidate).unwrap();
    for secret in [
        "SYNTHETIC-DO-NOT-PERSIST",
        "SYNTHETIC-NESTED",
        "SYNTHETIC-ARRAY",
        "SYNTHETIC-CHILD",
    ] {
        assert!(!encoded.contains(secret));
    }
    let schema = &candidate.template.schema;
    assert_eq!(schema["properties"]["key"]["type"], "string");
    assert_eq!(schema["properties"]["attempts"]["type"], "integer");
    assert_eq!(schema["properties"]["ratio"]["type"], "number");
    assert_eq!(schema["properties"]["enabled"]["type"], "boolean");
    assert_eq!(schema["properties"]["unset"]["type"], "null");
    assert!(schema["properties"]["empty"].get("items").is_none());
    assert!(schema.get("required").is_none());
    assert!(schema.get("additionalProperties").is_none());
    assert!(schema["properties"]["nested"].get("required").is_none());
    let pointers: Vec<_> = candidate
        .template
        .bindings
        .iter()
        .map(|binding| binding.pointer.as_str())
        .collect();
    assert_eq!(
        pointers,
        ["/array/0", "/array/3/secret", "/key", "/nested/token"]
    );
    assert!(!candidate.template.defaults.bearer_prefix);
    assert!(!candidate.template.defaults.replace_variables);
}

#[test]
fn inferred_template_requires_explicit_confirmation_and_nonempty_selection() {
    let mut candidate =
        templates::infer_candidate(br#"{"key":"synthetic"}"#, identity(), "Candidate".into())
            .unwrap();
    assert_eq!(
        code(templates::validate_template(&candidate.template)),
        "TEMPLATE_CONFIRM_REQUIRED"
    );
    candidate.requires_confirmation = false; // An input flag is not approval.
    assert_eq!(
        code(templates::confirm_candidate(candidate.clone(), false)),
        "TEMPLATE_CONFIRM_REQUIRED"
    );
    assert_eq!(
        code(templates::confirm_candidate(candidate.clone(), true)),
        "TEMPLATE_CONFIRM_REQUIRED"
    );
    candidate.template.write_allowlist.push("/key".into());
    let accepted = templates::confirm_candidate(candidate, true).unwrap();
    assert!(accepted.source.confirmed);
    assert_eq!(accepted.source.kind, SchemaSourceKind::SampleInferred);
    // Optional fields and unknown fields remain allowed after inference.
    templates::validate_config(&accepted, br#"{"other":123}"#).unwrap();
}

#[test]
fn inferred_bindings_escape_json_pointers_exactly() {
    let candidate = templates::infer_candidate(
        br#"{"a/b":{"~key":"synthetic"},"":"synthetic-empty-name"}"#,
        identity(),
        "Candidate".into(),
    )
    .unwrap();
    let pointers: Vec<_> = candidate
        .template
        .bindings
        .iter()
        .map(|binding| binding.pointer.as_str())
        .collect();
    assert_eq!(pointers, ["/", "/a~1b/~0key"]);
}

#[test]
fn patch_changes_only_allowed_existing_string_bytes_and_preserves_jsonc() {
    let original = b"\xef\xbb\xbf{\r\n  // retain comment\r\n  \"key\": \"synthetic-old\", \"other\": 1e+03,\r\n}\r\n";
    let definition = template(
        json!({"type":"object", "properties":{"key":{"type":"string"}, "other":{"type":"number"}}}),
    );
    let result =
        templates::prepare_patch(&definition, original, &[edit("/key", "synthetic-new")]).unwrap();
    let expected = String::from_utf8_lossy(original).replace("synthetic-old", "synthetic-new");
    assert_eq!(result.bytes.as_slice(), expected.as_bytes());
    assert!(!serde_json::to_string(&result.fields)
        .unwrap()
        .contains("synthetic-new"));
    assert!(!serde_json::to_string(&result.fields)
        .unwrap()
        .contains("synthetic-old"));
}

#[test]
fn patch_requires_binding_and_allowlist_independently() {
    let mut definition = template(json!({"type":"object"}));
    definition.bindings.push(FieldBinding {
        name: "other".into(),
        pointer: "/other".into(),
    });
    assert_eq!(
        code(templates::prepare_patch(
            &definition,
            br#"{"key":"a","other":"b"}"#,
            &[edit("/other", "c")]
        )),
        "TEMPLATE_WRITE_DENIED"
    );
    definition.write_allowlist.push("/unbound".into());
    assert_eq!(
        code(templates::validate_template(&definition)),
        "TEMPLATE_FORMAT"
    );
}

#[test]
fn duplicate_allowlist_or_binding_is_rejected() {
    let mut definition = template(json!({"type":"object"}));
    definition.write_allowlist.push("/key".into());
    assert_eq!(
        code(templates::validate_template(&definition)),
        "TEMPLATE_FORMAT"
    );
    definition.write_allowlist.pop();
    definition.bindings.push(FieldBinding {
        name: "another".into(),
        pointer: "/key".into(),
    });
    assert_eq!(
        code(templates::validate_template(&definition)),
        "TEMPLATE_FORMAT"
    );
}

#[test]
fn duplicate_edits_are_rejected_and_original_remains_unchanged() {
    let definition = template(json!({"type":"object"}));
    let original = br#"{"key":"original"}"#;
    assert_eq!(
        code(templates::prepare_patch(
            &definition,
            original,
            &[edit("/key", "a"), edit("/key", "b")]
        )),
        "FIELD_AMBIGUOUS"
    );
    assert_eq!(original, br#"{"key":"original"}"#);
}

#[test]
fn patch_never_creates_paths_or_coerces_nonstring_values() {
    let definition = template(json!({"type":"object"}));
    for original in [
        br#"{"key":null}"#.as_slice(),
        br#"{"key":1}"#,
        br#"{"key":{}}"#,
        br#"{"key":[]}"#,
    ] {
        assert_eq!(
            code(templates::prepare_patch(
                &definition,
                original,
                &[edit("/key", "a")]
            )),
            "FIELD_TYPE"
        );
    }
    assert_eq!(
        code(templates::prepare_patch(
            &definition,
            br#"{}"#,
            &[edit("/key", "a")]
        )),
        "FIELD_MISSING"
    );
}

#[test]
fn wildcard_is_literal_and_does_not_authorize_other_leaves() {
    let mut definition = template(json!({"type":"object"}));
    definition.bindings[0].pointer = "/auth/*".into();
    definition.write_allowlist[0] = "/auth/*".into();
    assert_eq!(
        code(templates::prepare_patch(
            &definition,
            br#"{"auth":{"token":"old"}}"#,
            &[edit("/auth/token", "new")]
        )),
        "TEMPLATE_WRITE_DENIED"
    );
    assert_eq!(
        code(templates::prepare_patch(
            &definition,
            br#"{"auth":{"token":"old"}}"#,
            &[edit("/auth/*", "new")]
        )),
        "FIELD_MISSING"
    );
}

#[test]
fn schema_is_validated_before_configuration_or_requests() {
    let definition = template(json!({"type":"not-a-json-schema-type"}));
    assert_eq!(
        code(templates::prepare_patch(
            &definition,
            b"invalid config",
            &[edit("/not-allowed", "synthetic")]
        )),
        "SCHEMA_INVALID"
    );
}

#[test]
fn full_patched_config_validation_catches_unrelated_structural_drift() {
    let definition = template(json!({
        "type":"object", "required":["key", "version"],
        "properties":{"key":{"type":"string"},"version":{"type":"integer", "minimum":1}},
        "additionalProperties":false
    }));
    for original in [
        br#"{"key":"old"}"#.as_slice(),
        br#"{"key":"old","version":"wrong"}"#,
        br#"{"key":"old","version":0}"#,
        br#"{"key":"old","version":1,"unexpected":true}"#,
    ] {
        assert_eq!(
            code(templates::prepare_patch(
                &definition,
                original,
                &[edit("/key", "new")]
            )),
            "SCHEMA_DRIFT"
        );
    }
    templates::prepare_patch(
        &definition,
        br#"{"key":"old","version":1}"#,
        &[edit("/key", "new")],
    )
    .unwrap();
}

#[test]
fn validation_applies_to_final_patch_and_can_repair_an_invalid_string() {
    let definition = template(json!({"properties":{"key":{"type":"string", "minLength":4}}}));
    assert_eq!(
        code(templates::validate_config(&definition, br#"{"key":"x"}"#)),
        "SCHEMA_DRIFT"
    );
    templates::prepare_patch(&definition, br#"{"key":"x"}"#, &[edit("/key", "longer")]).unwrap();
    assert_eq!(
        code(templates::prepare_patch(
            &definition,
            br#"{"key":"valid"}"#,
            &[edit("/key", "x")]
        )),
        "SCHEMA_DRIFT"
    );
}

#[test]
fn no_op_and_protected_variables_still_validate_entire_document() {
    let definition = template(json!({"required":["version"]}));
    assert_eq!(
        code(templates::prepare_patch(
            &definition,
            br#"{"key":"same"}"#,
            &[edit("/key", "same")]
        )),
        "SCHEMA_DRIFT"
    );
    assert_eq!(
        code(templates::prepare_patch(
            &definition,
            br#"{"key":"${SYNTHETIC_ENV}"}"#,
            &[edit("/key", "new")]
        )),
        "SCHEMA_DRIFT"
    );
    assert_eq!(
        code(templates::prepare_patch(
            &definition,
            br#"{"key":"same"}"#,
            &[]
        )),
        "SCHEMA_DRIFT"
    );
}

#[test]
fn variables_are_preserved_by_default_and_bearer_is_normalized() {
    let definition = template(json!({"type":"object"}));
    let original = br#"{"key":"${SYNTHETIC_ENV}"}"#;
    let result = templates::prepare_patch(&definition, original, &[edit("/key", "new")]).unwrap();
    assert_eq!(result.bytes.as_slice(), original);
    let mut request = edit("/key", "Bearer Bearer synthetic");
    request.bearer = true;
    request.replace_variables = true;
    let result = templates::prepare_patch(&definition, original, &[request]).unwrap();
    assert_eq!(
        jsonc::parse_value(&result.bytes).unwrap()["key"],
        "Bearer synthetic"
    );
}

#[test]
fn imported_sample_values_and_free_text_are_rejected_without_sanitizing_schema() {
    for keyword in [
        "default",
        "examples",
        "example",
        "const",
        "enum",
        "title",
        "description",
        "$comment",
    ] {
        let mut child = json!({"type":"string"});
        child[keyword] = json!("SYNTHETIC-SECRET");
        let definition = template(json!({"properties":{"key":child}}));
        let before = definition.schema.clone();
        let error = templates::validate_template(&definition).unwrap_err();
        assert_eq!(error.code, "TEMPLATE_LITERAL");
        assert!(!error.to_string().contains("SYNTHETIC-SECRET"));
        assert_eq!(definition.schema, before);
    }
}

#[test]
fn a_config_property_named_default_or_const_is_not_a_schema_annotation() {
    let definition =
        template(json!({"properties":{"default":{"type":"string"}, "const":{"type":"string"}}}));
    templates::validate_template(&definition).unwrap();
}

#[test]
fn external_refs_are_blocked_in_all_recognized_schema_locations() {
    for reference in [
        "https://example.invalid/schema.json",
        "file:///etc/passwd",
        "../local.json",
        "C:\\private.json",
        "//example.invalid/a",
    ] {
        let definition = template(json!({"$defs":{"unused":{"$ref":reference}}, "type":"object"}));
        assert_eq!(
            code(templates::validate_template(&definition)),
            "SCHEMA_EXTERNAL_REF"
        );
        let definition = template(json!({"properties":{"key":{"$ref":reference}}}));
        assert_eq!(
            code(templates::validate_template(&definition)),
            "SCHEMA_EXTERNAL_REF"
        );
    }
}

#[test]
fn bundled_local_refs_validate_without_fetching() {
    let definition = template(json!({
        "$defs":{"keyString":{"type":"string", "minLength":3}},
        "type":"object", "properties":{"key":{"$ref":"#/$defs/keyString"}}
    }));
    templates::validate_template(&definition).unwrap();
    templates::prepare_patch(&definition, br#"{"key":"old"}"#, &[edit("/key", "new")]).unwrap();
    assert_eq!(
        code(templates::prepare_patch(
            &definition,
            br#"{"key":"old"}"#,
            &[edit("/key", "x")]
        )),
        "SCHEMA_DRIFT"
    );
}

#[test]
fn cyclic_missing_anchor_encoded_and_nonschema_refs_fail_closed() {
    for schema in [
        json!({"$ref":"#"}),
        json!({"$defs":{"a":{"$ref":"#/$defs/b"},"b":{"$ref":"#/$defs/a"}}, "$ref":"#/$defs/a"}),
        json!({"$ref":"#/$defs/missing"}),
        json!({"$ref":"#namedAnchor"}),
        json!({"$ref":"#/%24defs/key"}),
        json!({"$ref":"#/type", "type":"object"}),
    ] {
        assert_eq!(
            code(templates::validate_template(&template(schema))),
            "SCHEMA_REFERENCE"
        );
    }
}

#[test]
fn rebasing_and_unknown_keywords_are_never_ignored() {
    for schema in [
        json!({"$id":"https://example.invalid/rebased.json"}),
        json!({"$vocabulary":{"https://example.invalid/vocab":true}}),
        json!({"$dynamicRef":"#key"}),
        json!({"unevaluatedProperties":false}),
        json!({"contentEncoding":"base64"}),
        json!({"minLenght":3}),
        json!({"properties":{"key":{"$schema":SCHEMA_DIALECT}}}),
    ] {
        assert_eq!(
            code(templates::validate_template(&template(schema))),
            "SCHEMA_UNSUPPORTED"
        );
    }
}

#[test]
fn missing_or_unsupported_dialect_never_falls_back() {
    let mut definition = template(json!({"type":"object"}));
    definition.schema.as_object_mut().unwrap().remove("$schema");
    assert_eq!(
        code(templates::validate_template(&definition)),
        "SCHEMA_DIALECT"
    );
    for dialect in [
        "http://json-schema.org/draft-07/schema#",
        "https://example.invalid/custom-meta",
    ] {
        definition.schema["$schema"] = json!(dialect);
        assert_eq!(
            code(templates::validate_template(&definition)),
            "SCHEMA_DIALECT"
        );
    }
}

#[test]
fn malformed_keyword_values_fail_meta_validation() {
    for schema in [
        json!({"required":"key"}),
        json!({"required":["key", "key"]}),
        json!({"maxItems":-1}),
        json!({"minimum":"not-a-number"}),
        json!({"multipleOf":0}),
        json!({"properties":{"key":123}}),
        json!({"prefixItems":"not-an-array"}),
    ] {
        assert_eq!(
            code(templates::validate_template(&template(schema))),
            "SCHEMA_INVALID"
        );
    }
}

#[test]
fn formats_are_enforced_and_unknown_formats_fail() {
    let definition = template(json!({"properties":{"key":{"type":"string", "format":"email"}}}));
    assert_eq!(
        code(templates::prepare_patch(
            &definition,
            br#"{"key":"old@example.invalid"}"#,
            &[edit("/key", "invalid-email")]
        )),
        "SCHEMA_DRIFT"
    );
    let unknown = template(
        json!({"properties":{"key":{"type":"string", "format":"unknown-synthetic-format"}}}),
    );
    assert_eq!(
        code(templates::validate_template(&unknown)),
        "SCHEMA_INVALID"
    );
}

#[test]
fn regex_is_enforced_but_backtracking_features_fail_compilation() {
    let definition =
        template(json!({"properties":{"key":{"type":"string", "pattern":"^[a-z]+$"}}}));
    assert_eq!(
        code(templates::prepare_patch(
            &definition,
            br#"{"key":"old"}"#,
            &[edit("/key", "123")]
        )),
        "SCHEMA_DRIFT"
    );
    let unsupported = template(json!({"properties":{"key":{"pattern":"(?<=a)b"}}}));
    assert_eq!(
        code(templates::validate_template(&unsupported)),
        "SCHEMA_INVALID"
    );
}

#[test]
fn composite_object_array_and_conditional_constraints_are_enforced() {
    let definition = template(json!({
        "type":"object", "required":["key", "mode", "values"],
        "properties":{
            "key":{"type":"string"},
            "mode":{"type":"boolean"},
            "values":{"type":"array", "minItems":1, "uniqueItems":true, "items":{"type":"integer", "minimum":0}}
        },
        "if":{"properties":{"mode":{"type":"boolean"}},"required":["mode"]},
        "then":{"required":["values"]},
        "allOf":[{"not":{"required":["forbidden"]}}]
    }));
    templates::prepare_patch(
        &definition,
        br#"{"key":"old","mode":true,"values":[1,2]}"#,
        &[edit("/key", "new")],
    )
    .unwrap();
    for original in [
        br#"{"key":"old","mode":true,"values":[1,1]}"#.as_slice(),
        br#"{"key":"old","mode":true,"values":[-1]}"#,
        br#"{"key":"old","mode":true,"values":[]}"#,
        br#"{"key":"old","mode":true,"values":[1],"forbidden":0}"#,
    ] {
        assert_eq!(
            code(templates::prepare_patch(
                &definition,
                original,
                &[edit("/key", "new")]
            )),
            "SCHEMA_DRIFT"
        );
    }
}

#[test]
fn schema_errors_never_contain_the_instance_or_replacement_value() {
    let definition = template(json!({"properties":{"key":{"type":"string", "maxLength":1}}}));
    let result = templates::prepare_patch(
        &definition,
        br#"{"key":"SYNTHETIC-OLD-SECRET"}"#,
        &[edit("/key", "SYNTHETIC-NEW-SECRET")],
    );
    let error = match result {
        Err(error) => error,
        Ok(_) => panic!("Expected schema rejection"),
    };
    let encoded = serde_json::to_string(&error).unwrap();
    assert!(!encoded.contains("SYNTHETIC-OLD-SECRET"));
    assert!(!encoded.contains("SYNTHETIC-NEW-SECRET"));
    assert!(!encoded.contains("/key"));
}

#[test]
fn candidate_and_template_roundtrip_with_no_arbitrary_extra_fields() {
    let candidate =
        templates::infer_candidate(br#"{"key":"synthetic"}"#, identity(), "Candidate".into())
            .unwrap();
    let encoded = serde_json::to_value(&candidate).unwrap();
    let decoded: templates::TemplateCandidate = serde_json::from_value(encoded).unwrap();
    assert_eq!(decoded.template.schema, candidate.template.schema);
    let mut encoded = serde_json::to_value(template(json!({"type":"object"}))).unwrap();
    encoded["secret"] = json!("synthetic-hidden-secret");
    assert!(serde_json::from_value::<Template>(encoded).is_err());
    let mut encoded = serde_json::to_value(template(json!({"type":"object"}))).unwrap();
    encoded["defaults"]["key"] = json!("synthetic-hidden-secret");
    assert!(serde_json::from_value::<Template>(encoded).is_err());
}

#[test]
fn identification_metadata_cannot_smuggle_paths_or_select_writes() {
    for file_name in [
        "../config.json",
        "C:\\config.json",
        "/etc/config",
        "\\\\host\\config",
        ".",
        "..",
    ] {
        let mut definition = template(json!({"type":"object"}));
        definition.application.config_file_names = vec![file_name.into()];
        assert_eq!(
            code(templates::validate_template(&definition)),
            "TEMPLATE_FORMAT"
        );
    }
}

#[test]
fn root_binding_is_rejected_even_under_permissive_schema() {
    let mut definition = template(json!({}));
    definition.bindings[0].pointer.clear();
    definition.write_allowlist[0].clear();
    assert_eq!(
        code(templates::validate_template(&definition)),
        "TEMPLATE_FORMAT"
    );
}

#[test]
fn oversized_or_deep_schema_is_rejected_before_compilation() {
    let mut nested = json!({"type":"string"});
    for _ in 0..50 {
        nested = json!({"properties":{"nested":nested}});
    }
    assert_eq!(
        code(templates::validate_template(&template(nested))),
        "SCHEMA_LIMIT"
    );
    let large = template(json!({"pattern":"x".repeat(templates::MAX_TEMPLATE_BYTES + 1)}));
    assert_eq!(code(templates::validate_template(&large)), "SCHEMA_LIMIT");
}

#[test]
fn oversized_inference_and_duplicate_json_are_rejected() {
    let sample = serde_json::to_vec(&json!({"array":vec![0; 5000]})).unwrap();
    assert_eq!(
        code(templates::infer_candidate(
            &sample,
            identity(),
            "Candidate".into()
        )),
        "SCHEMA_LIMIT"
    );
    assert_eq!(
        code(templates::infer_candidate(
            br#"{"key":"a","key":"b"}"#,
            identity(),
            "Candidate".into()
        )),
        "JSON_DUPLICATE"
    );
}

#[test]
fn utf16_jsonc_is_validated_without_changing_encoding() {
    let definition = template(json!({"type":"object", "properties":{"key":{"type":"string"}}}));
    let original = "{\r\n // synthetic comment\r\n \"key\": \"old\",\r\n}";
    for little_endian in [true, false] {
        let mut bytes = if little_endian {
            vec![0xff, 0xfe]
        } else {
            vec![0xfe, 0xff]
        };
        for unit in original.encode_utf16() {
            bytes.extend_from_slice(&if little_endian {
                unit.to_le_bytes()
            } else {
                unit.to_be_bytes()
            });
        }
        let result = templates::prepare_patch(&definition, &bytes, &[edit("/key", "new")]).unwrap();
        assert_eq!(&result.bytes[..2], &bytes[..2]);
        assert_eq!(jsonc::parse_value(&result.bytes).unwrap()["key"], "new");
    }
}

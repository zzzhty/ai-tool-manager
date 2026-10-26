use atm_core::distribution::{hooks, runtime::PreparedRuntime};
use serde_json::{json, Value};
use std::{collections::BTreeMap, path::PathBuf};

fn retired_fixture() -> (PathBuf, hooks::HookOwnership, Value) {
    let root = std::env::temp_dir().join("TEST_ONLY retired hooks 空间");
    let target = root.join("hooks.json");
    let groups: BTreeMap<_, _> = hooks::EVENTS.into_iter().map(|event| (
        event.to_owned(), json!({"hooks":[{"type":"command","command":"TEST_ONLY old collector","statusMessage":format!("Watcher skill: observe {event}")}]}),
    )).collect();
    let owner = hooks::HookOwnership {
        schema_version: 1,
        owner: "atm-harness:watcher".into(),
        target: target.clone(),
        groups: groups.clone(),
        runtime: PreparedRuntime {
            id: "watcher".into(),
            identity: "old-runtime".into(),
            root: root.join("venv"),
            python: root.join("venv/bin/python"),
            external: false,
        },
        bundle_root: root,
        hooks_preexisted: true,
        preserved_empty_events: vec!["Stop".into(), "Unknown".into()],
    };
    let mut value = json!({"userField":{"keep":true},"hooks":{"Unknown":[],"Stop":[],"SessionStart":[{"matcher":"foreign","hooks":[{"type":"command","command":"user-owned"}]}]}});
    for (event, group) in groups {
        value["hooks"]
            .as_object_mut()
            .unwrap()
            .entry(event)
            .or_insert(json!([]))
            .as_array_mut()
            .unwrap()
            .push(group);
    }
    (target, owner, value)
}

#[test]
fn removal_preserves_foreign_entries_and_repeats_without_runtime_or_source() {
    let (target, owner, current) = retired_fixture();
    let bytes = serde_json::to_vec(&current).unwrap();
    let plan =
        hooks::plan_removal(&target, Some(&bytes), Some(&owner), &owner.bundle_root).unwrap();
    let bytes = &plan.artifact.unwrap().bytes;
    let after: Value = serde_json::from_slice(bytes).unwrap();
    assert_eq!(
        after,
        json!({"userField":{"keep":true},"hooks":{"Unknown":[],"Stop":[],"SessionStart":[{"matcher":"foreign","hooks":[{"type":"command","command":"user-owned"}]}]}})
    );
    assert!(plan.ownership.is_none());
    assert!(
        hooks::plan_removal(&target, Some(bytes), None, &owner.bundle_root)
            .unwrap()
            .artifact
            .is_none()
    );
}

#[test]
fn no_receipt_and_modified_or_duplicate_owned_groups_fail_closed() {
    let (target, owner, current) = retired_fixture();
    let bytes = serde_json::to_vec(&current).unwrap();
    assert_eq!(
        hooks::plan_removal(&target, Some(&bytes), None, &owner.bundle_root)
            .unwrap_err()
            .code,
        "HARNESS_HOOK_CONFLICT"
    );
    for duplicate in [false, true] {
        let mut altered = current.clone();
        if duplicate {
            altered["hooks"]["Stop"]
                .as_array_mut()
                .unwrap()
                .push(owner.groups["Stop"].clone());
        } else {
            altered["hooks"]["Stop"][0]["hooks"][0]["timeoutSec"] = json!(22);
        }
        assert_eq!(
            hooks::plan_removal(
                &target,
                Some(&serde_json::to_vec(&altered).unwrap()),
                Some(&owner),
                &owner.bundle_root
            )
            .unwrap_err()
            .code,
            "HARNESS_HOOK_CONFLICT"
        );
    }
    assert!(hooks::plan_removal(&target, None, None, &owner.bundle_root)
        .unwrap()
        .artifact
        .is_none());
}

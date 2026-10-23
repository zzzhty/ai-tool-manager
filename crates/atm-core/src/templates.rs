//! Offline, value-free templates. This module never opens a file or performs a write.
//!
//! Application identification is descriptive, never authorization to locate/write a
//! file. Field bindings describe candidates; the separate allowlist authorizes exact
//! existing string leaves. Defaults configure patch behavior, not config values.
//! Only the explicitly checked JSON Schema 2020-12 profile is accepted. Unsupported
//! keywords, references, and dialects fail closed rather than weakening a schema.
use crate::{jsonc, Error, Result, MAX_CONFIG_BYTES};
use jsonschema::{Draft, PatternOptions, Retrieve, Uri, Validator};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use uuid::Uuid;
use zeroize::Zeroize;

pub const SCHEMA_DIALECT: &str = "https://json-schema.org/draft/2020-12/schema";
pub const MAX_TEMPLATE_BYTES: usize = 1024 * 1024;
const MAX_SCHEMA_NODES: usize = 4096;
const MAX_SCHEMA_DEPTH: usize = 48;
const MAX_BINDINGS: usize = 1024;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ApplicationIdentity {
    pub id: String,
    pub display_name: String,
    /// Filename hints only. No paths, discovery rules, or automatic file access.
    #[serde(default)]
    pub config_file_names: Vec<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum SchemaSourceKind {
    UserAuthored,
    ProvidedSchema,
    SampleInferred,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SchemaSource {
    /// Provenance is descriptive, not a claim that a schema is official.
    pub kind: SchemaSourceKind,
    pub version: String,
    /// Set by the explicit review/save flow, never by inference.
    #[serde(default)]
    pub confirmed: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FieldBinding {
    pub name: String,
    pub pointer: String,
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PatchDefaults {
    #[serde(default)]
    pub bearer_prefix: bool,
    #[serde(default)]
    pub replace_variables: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Template {
    pub format_version: u32,
    pub id: Uuid,
    pub name: String,
    pub application: ApplicationIdentity,
    pub source: SchemaSource,
    pub bindings: Vec<FieldBinding>,
    pub write_allowlist: Vec<String>,
    #[serde(default)]
    pub defaults: PatchDefaults,
    pub schema: Value,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TemplateCandidate {
    pub template: Template,
    pub requires_confirmation: bool,
    pub warnings: Vec<String>,
}

/// Inference preserves field names and candidate types/structure, never sample
/// scalar values. It makes no claim about official requirements or allowed extras.
/// The caller must show the schema and selected pointers for review before saving.
pub fn infer_candidate(
    original: &[u8],
    application: ApplicationIdentity,
    name: String,
) -> Result<TemplateCandidate> {
    check_config_size(original)?;
    let sample = ConfigValue(jsonc::parse_value(original)?);
    let mut bindings = Vec::new();
    let mut visited = 0;
    let mut schema = infer_node(&sample.0, "", &mut bindings, 0, &mut visited)?;
    let object = schema.as_object_mut().ok_or(invalid_template())?;
    object.insert("$schema".into(), Value::String(SCHEMA_DIALECT.into()));
    let template = Template {
        format_version: 1,
        id: Uuid::new_v4(),
        name,
        application,
        source: SchemaSource {
            kind: SchemaSourceKind::SampleInferred,
            version: "sample-structure-v1".into(),
            confirmed: false,
        },
        bindings,
        write_allowlist: Vec::new(),
        defaults: PatchDefaults::default(),
        schema,
    };
    validate_metadata(&template, false)?;
    let _ = compile_schema(&template.schema)?;
    Ok(TemplateCandidate {
        template,
        requires_confirmation: true,
        warnings: vec![
            "仅从样本观察到候选类型与结构，不代表官方规范。".into(),
            "未推断必填字段，也未禁止未知字段；保存前请核对 schema 并选择允许写入的精确字段。"
                .into(),
            "模板保留属性名与路径；请确认这些名称本身不含密钥或个人信息。样本值不会保存。".into(),
        ],
    })
}

/// The boolean must come from the current explicit review/save action, not a
/// deserialized candidate flag. Review includes schema, provenance, and allowlist.
pub fn confirm_candidate(mut candidate: TemplateCandidate, confirmed: bool) -> Result<Template> {
    if !confirmed {
        return Err(Error::new(
            "TEMPLATE_CONFIRM_REQUIRED",
            "须确认候选结构和写入白名单后才能保存可复用模板。",
        ));
    }
    candidate.template.source.confirmed = true;
    validate_template(&candidate.template)?;
    Ok(candidate.template)
}

pub fn validate_template(template: &Template) -> Result<()> {
    validate_metadata(template, true)?;
    let _ = compile_schema(&template.schema)?;
    Ok(())
}

/// Validate the complete current configuration. Errors intentionally omit schema
/// error text, instance values, and instance paths, all of which can contain keys.
pub fn validate_config(template: &Template, original: &[u8]) -> Result<()> {
    validate_metadata(template, true)?;
    let validator = compile_schema(&template.schema)?;
    validate_bytes(&validator, original)
}

/// Build a byte-preserving, exact-string patch in memory and validate the entire
/// resulting config before returning any replacement bytes to the batch writer.
/// There is deliberately no object merge, field creation, deletion, or coercion.
pub fn prepare_patch(
    template: &Template,
    original: &[u8],
    requests: &[jsonc::EditRequest],
) -> Result<jsonc::EditResult> {
    validate_metadata(template, true)?;
    // Meta-validate and compile first, even when requests are empty or invalid.
    let validator = compile_schema(&template.schema)?;
    check_config_size(original)?;
    if requests.len() > MAX_BINDINGS {
        return Err(invalid_template());
    }
    for request in requests {
        let pointer = checked_pointer(&request.pointer)?;
        if !template.write_allowlist.contains(&pointer)
            || !template
                .bindings
                .iter()
                .any(|binding| binding.pointer == pointer)
        {
            return Err(Error::new(
                "TEMPLATE_WRITE_DENIED",
                "字段不在该模板已确认的精确写入白名单中。",
            ));
        }
    }
    let result = jsonc::edit(original, requests)?;
    validate_bytes(&validator, &result.bytes)?;
    Ok(result)
}

fn check_config_size(bytes: &[u8]) -> Result<()> {
    if bytes.len() > MAX_CONFIG_BYTES {
        return Err(Error::new("CONFIG_LIMIT", "配置文件超过大小上限。"));
    }
    Ok(())
}

fn validate_bytes(validator: &Validator, bytes: &[u8]) -> Result<()> {
    check_config_size(bytes)?;
    let instance = ConfigValue(jsonc::parse_value(bytes)?);
    if !validator.is_valid(&instance.0) {
        return Err(Error::new(
            "SCHEMA_DRIFT",
            "完整配置不符合已确认的 schema，已拒绝写入；请检查结构漂移或模板版本。",
        ));
    }
    Ok(())
}

fn invalid_template() -> Error {
    Error::new(
        "TEMPLATE_FORMAT",
        "模板元数据、绑定或白名单无效，或超过限制。",
    )
}

fn valid_text(value: &str, max: usize) -> bool {
    !value.trim().is_empty() && value.len() <= max && !value.chars().any(char::is_control)
}

fn checked_pointer(pointer: &str) -> Result<String> {
    if pointer.is_empty() || pointer.len() > 4096 || pointer.chars().any(char::is_control) {
        return Err(invalid_template());
    }
    let normalized = jsonc::normalize(pointer)?;
    if normalized != pointer {
        return Err(invalid_template());
    }
    Ok(normalized)
}

fn validate_metadata(template: &Template, reusable: bool) -> Result<()> {
    if template.format_version != 1
        || template.id.is_nil()
        || !valid_text(&template.name, 128)
        || !valid_text(&template.application.id, 128)
        || !valid_text(&template.application.display_name, 128)
        || !valid_text(&template.source.version, 128)
        || template.application.config_file_names.len() > 32
        || template.bindings.len() > MAX_BINDINGS
        || template.write_allowlist.len() > MAX_BINDINGS
    {
        return Err(invalid_template());
    }
    for name in &template.application.config_file_names {
        if !valid_text(name, 255)
            || name
                .chars()
                .any(|character| matches!(character, '/' | '\\' | ':'))
            || matches!(name.as_str(), "." | "..")
        {
            return Err(invalid_template());
        }
    }
    let mut names = BTreeSet::new();
    let mut pointers = BTreeSet::new();
    for binding in &template.bindings {
        if !valid_text(&binding.name, 128)
            || !names.insert(binding.name.as_str())
            || !pointers.insert(checked_pointer(&binding.pointer)?)
        {
            return Err(invalid_template());
        }
    }
    let mut allowed = BTreeSet::new();
    for pointer in &template.write_allowlist {
        let pointer = checked_pointer(pointer)?;
        if !pointers.contains(&pointer) || !allowed.insert(pointer) {
            return Err(invalid_template());
        }
    }
    if reusable && (!template.source.confirmed || allowed.is_empty()) {
        return Err(Error::new(
            "TEMPLATE_CONFIRM_REQUIRED",
            "须确认模板来源、schema 和至少一个精确写入字段。",
        ));
    }
    check_schema_bounds(&template.schema)?;
    Ok(())
}

/// No network, filesystem, custom URL scheme, or external registry access, even
/// if another dependency accidentally unifies jsonschema's resolving features.
struct DenyRetrieval;
impl Retrieve for DenyRetrieval {
    fn retrieve(
        &self,
        _uri: &Uri<String>,
    ) -> std::result::Result<Value, Box<dyn std::error::Error + Send + Sync>> {
        Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            "External schema retrieval disabled",
        )
        .into())
    }
}

fn compile_schema(schema: &Value) -> Result<Validator> {
    check_schema_bounds(schema)?;
    // An explicit dialect prevents draft fallback and forbids custom metaschema
    // retrieval. Nested dialect changes are rejected by inspect_schema.
    if schema.get("$schema").and_then(Value::as_str) != Some(SCHEMA_DIALECT) {
        return Err(Error::new(
            "SCHEMA_DIALECT",
            "仅支持显式声明的 JSON Schema 2020-12 本地安全子集。",
        ));
    }
    let mut graph = SchemaGraph::default();
    inspect_schema(schema, "", &mut graph)?;
    graph.validate()?;
    // The built-in standard metaschema is bundled with jsonschema. Never expose
    // the validator's detailed error, which may include supplied schema values.
    jsonschema::meta::validate(schema).map_err(|_| {
        Error::new(
            "SCHEMA_INVALID",
            "JSON Schema 本身不符合其元 schema，已拒绝使用。",
        )
    })?;
    jsonschema::options()
        .with_draft(Draft::Draft202012)
        .with_retriever(DenyRetrieval)
        .with_pattern_options(
            PatternOptions::regex()
                .size_limit(MAX_TEMPLATE_BYTES)
                .dfa_size_limit(MAX_TEMPLATE_BYTES),
        )
        .should_validate_formats(true)
        .should_ignore_unknown_formats(false)
        .build(schema)
        .map_err(|_| {
            Error::new(
                "SCHEMA_INVALID",
                "Schema 无法安全编译；请检查引用、格式或正则表达式。",
            )
        })
}

fn check_schema_bounds(schema: &Value) -> Result<()> {
    let mut stack = vec![(schema, 0usize)];
    let mut nodes = 0usize;
    let mut bytes = 0usize;
    while let Some((value, depth)) = stack.pop() {
        nodes += 1;
        bytes = bytes.saturating_add(8);
        if depth > MAX_SCHEMA_DEPTH || nodes > MAX_SCHEMA_NODES || bytes > MAX_TEMPLATE_BYTES {
            return Err(Error::new(
                "SCHEMA_LIMIT",
                "Schema 大小、深度或节点数量超过安全上限。",
            ));
        }
        match value {
            Value::Object(properties) => {
                for (name, child) in properties {
                    bytes = bytes.saturating_add(name.len());
                    stack.push((child, depth + 1));
                }
            }
            Value::Array(items) => stack.extend(items.iter().map(|child| (child, depth + 1))),
            Value::String(text) => bytes = bytes.saturating_add(text.len()),
            Value::Number(number) => bytes = bytes.saturating_add(number.to_string().len()),
            _ => {}
        }
        if bytes > MAX_TEMPLATE_BYTES {
            return Err(Error::new(
                "SCHEMA_LIMIT",
                "Schema 大小、深度或节点数量超过安全上限。",
            ));
        }
    }
    Ok(())
}

#[derive(Default)]
struct SchemaGraph {
    children: BTreeMap<String, Vec<String>>,
    references: Vec<(String, String)>,
}
impl SchemaGraph {
    fn child(&mut self, parent: &str, child: &str) {
        self.children
            .entry(parent.into())
            .or_default()
            .push(child.into());
    }

    fn validate(mut self) -> Result<()> {
        for (from, target) in self.references {
            if !self.children.contains_key(&target) {
                return Err(Error::new(
                    "SCHEMA_REFERENCE",
                    "本地引用必须指向同一文档中已识别的 schema 节点。",
                ));
            }
            self.children.entry(from).or_default().push(target);
        }
        let mut done = BTreeSet::new();
        let mut visiting = BTreeSet::new();
        for pointer in self.children.keys() {
            check_acyclic(pointer, &self.children, &mut visiting, &mut done, 0)?;
        }
        Ok(())
    }
}

fn check_acyclic(
    node: &str,
    edges: &BTreeMap<String, Vec<String>>,
    visiting: &mut BTreeSet<String>,
    done: &mut BTreeSet<String>,
    depth: usize,
) -> Result<()> {
    if done.contains(node) {
        return Ok(());
    }
    if depth > MAX_SCHEMA_DEPTH || !visiting.insert(node.into()) {
        return Err(Error::new(
            "SCHEMA_REFERENCE",
            "循环引用或过深引用不在支持的安全 schema 范围内。",
        ));
    }
    if let Some(children) = edges.get(node) {
        for child in children {
            check_acyclic(child, edges, visiting, done, depth + 1)?;
        }
    }
    visiting.remove(node);
    done.insert(node.into());
    Ok(())
}

fn join_pointer(parent: &str, segment: &str) -> String {
    format!("{parent}/{}", segment.replace('~', "~0").replace('/', "~1"))
}

fn inspect_schema(schema: &Value, location: &str, graph: &mut SchemaGraph) -> Result<()> {
    graph.children.entry(location.into()).or_default();
    if schema.is_boolean() {
        return Ok(());
    }
    let Some(object) = schema.as_object() else {
        return Err(Error::new(
            "SCHEMA_INVALID",
            "Schema 节点必须为对象或布尔值。",
        ));
    };
    for (keyword, value) in object {
        let here = join_pointer(location, keyword);
        match keyword.as_str() {
            "$schema" if location.is_empty() => {}
            "$ref" => {
                let reference = value.as_str().ok_or(Error::new(
                    "SCHEMA_REFERENCE",
                    "Schema 引用必须为本地 JSON Pointer。",
                ))?;
                let Some(pointer) = reference.strip_prefix('#') else {
                    return Err(Error::new(
                        "SCHEMA_EXTERNAL_REF",
                        "外部 schema 引用被禁用；不访问网络或外部文件。",
                    ));
                };
                // URI-encoded pointers and anchors are deliberately unsupported.
                if pointer.contains('%')
                    || pointer.chars().any(char::is_whitespace)
                    || jsonc::normalize(pointer).is_err()
                {
                    return Err(Error::new(
                        "SCHEMA_REFERENCE",
                        "仅支持未经 URI 编码的文档内 JSON Pointer 引用。",
                    ));
                }
                graph.references.push((location.into(), pointer.into()));
            }
            "$defs" | "properties" | "patternProperties" | "dependentSchemas" => {
                let properties = value
                    .as_object()
                    .ok_or(Error::new("SCHEMA_INVALID", "Schema 映射必须为对象。"))?;
                for (name, child) in properties {
                    let pointer = join_pointer(&here, name);
                    graph.child(location, &pointer);
                    inspect_schema(child, &pointer, graph)?;
                }
            }
            "additionalProperties"
            | "propertyNames"
            | "items"
            | "contains"
            | "not"
            | "if"
            | "then"
            | "else" => {
                graph.child(location, &here);
                inspect_schema(value, &here, graph)?;
            }
            "prefixItems" | "allOf" | "anyOf" | "oneOf" => {
                let children = value
                    .as_array()
                    .ok_or(Error::new("SCHEMA_INVALID", "Schema 组合必须为数组。"))?;
                for (index, child) in children.iter().enumerate() {
                    let pointer = join_pointer(&here, &index.to_string());
                    graph.child(location, &pointer);
                    inspect_schema(child, &pointer, graph)?;
                }
            }
            "type" | "required" | "dependentRequired" | "minProperties" | "maxProperties"
            | "minItems" | "maxItems" | "uniqueItems" | "minContains" | "maxContains"
            | "minimum" | "maximum" | "exclusiveMinimum" | "exclusiveMaximum" | "multipleOf"
            | "minLength" | "maxLength" | "pattern" | "format" => {}
            "default" | "examples" | "example" | "const" | "enum" | "title" | "description"
            | "$comment" => {
                return Err(Error::new("TEMPLATE_LITERAL", "可复用 schema 禁止样本值、默认值、常量、枚举及自由文本注释；请手动提供无敏感值的结构约束。"));
            }
            _ => {
                return Err(Error::new(
                    "SCHEMA_UNSUPPORTED",
                    "Schema 含不支持的关键字或嵌套方言，已拒绝使用，不会忽略或放宽约束。",
                ));
            }
        }
    }
    Ok(())
}

fn infer_node(
    value: &Value,
    pointer: &str,
    bindings: &mut Vec<FieldBinding>,
    depth: usize,
    visited: &mut usize,
) -> Result<Value> {
    *visited += 1;
    if depth > MAX_SCHEMA_DEPTH || bindings.len() > MAX_BINDINGS || *visited > MAX_SCHEMA_NODES {
        return Err(Error::new(
            "SCHEMA_LIMIT",
            "样本结构过大，无法生成受限候选模板。",
        ));
    }
    Ok(match value {
        Value::Object(properties) => {
            let mut children = Map::new();
            for (name, child) in properties {
                children.insert(
                    name.clone(),
                    infer_node(
                        child,
                        &join_pointer(pointer, name),
                        bindings,
                        depth + 1,
                        visited,
                    )?,
                );
            }
            json!({ "type": "object", "properties": children })
        }
        Value::Array(items) => {
            let mut variants = Vec::new();
            for (index, child) in items.iter().enumerate() {
                let candidate = infer_node(
                    child,
                    &join_pointer(pointer, &index.to_string()),
                    bindings,
                    depth + 1,
                    visited,
                )?;
                if !variants.contains(&candidate) {
                    variants.push(candidate);
                }
            }
            match variants.len() {
                0 => json!({ "type": "array" }),
                1 => json!({ "type": "array", "items": variants.remove(0) }),
                _ => json!({ "type": "array", "items": { "anyOf": variants } }),
            }
        }
        Value::String(_) => {
            bindings.push(FieldBinding {
                name: format!("field{}", bindings.len() + 1),
                pointer: pointer.into(),
            });
            json!({ "type": "string" })
        }
        Value::Number(number) => {
            json!({ "type": if number.is_i64() || number.is_u64() { "integer" } else { "number" } })
        }
        Value::Bool(_) => json!({ "type": "boolean" }),
        Value::Null => json!({ "type": "null" }),
    })
}

/// serde_json::Value does not implement Zeroize. Limit string lifetimes and wipe
/// owned config strings/keys on every return path; numeric internals remain owned
/// by serde_json and are not guaranteed erased. No config Values are serialized
/// into any template or error response.
struct ConfigValue(Value);
impl Drop for ConfigValue {
    fn drop(&mut self) {
        wipe_value(&mut self.0);
    }
}
fn wipe_value(value: &mut Value) {
    match value {
        Value::String(text) => text.zeroize(),
        Value::Array(items) => items.iter_mut().for_each(wipe_value),
        Value::Object(properties) => {
            for (mut key, mut child) in std::mem::take(properties) {
                key.zeroize();
                wipe_value(&mut child);
            }
        }
        _ => {}
    }
}

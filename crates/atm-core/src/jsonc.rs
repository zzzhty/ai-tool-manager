//! Bounded JSONC parsing with source spans. Editing copies all unrelated original bytes.
use crate::{Error, Result, MASK, MAX_CONFIG_BYTES};
use serde::Serialize;
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use zeroize::Zeroizing;

pub fn segments(pointer: &str) -> Result<Vec<String>> {
    if pointer.is_empty() {
        return Ok(Vec::new());
    }
    if !pointer.starts_with('/') {
        return Err(Error::new(
            "POINTER_FORMAT",
            "须使用 JSON Pointer 精确字段。",
        ));
    }
    pointer[1..]
        .split('/')
        .map(|part| {
            let mut result = String::new();
            let mut chars = part.chars();
            while let Some(c) = chars.next() {
                if c != '~' {
                    result.push(c);
                } else {
                    match chars.next() {
                        Some('0') => result.push('~'),
                        Some('1') => result.push('/'),
                        _ => return Err(Error::new("POINTER_ESCAPE", "JSON Pointer 转义无效。")),
                    }
                }
            }
            Ok(result)
        })
        .collect()
}
pub fn normalize(pointer: &str) -> Result<String> {
    Ok(segments(pointer)?
        .iter()
        .map(|p| format!("/{}", p.replace('~', "~0").replace('/', "~1")))
        .collect())
}
pub fn has_variable(value: &str) -> bool {
    // Environment substitutions can appear inside a header or another literal.
    // Err on the side of preserving a reference until the user opts in.
    value.contains("${")
        || value.contains("$(")
        || value.contains("{{")
        || (value.len() > 2 && value.starts_with('%') && value.ends_with('%'))
        || value.split('%').skip(1).step_by(2).any(|part| {
            !part.is_empty()
                && part.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
                && value.contains(&format!("%{part}%"))
        })
}
pub fn bearer_value(secret: &str, enabled: bool) -> Result<Zeroizing<String>> {
    if !enabled {
        return Ok(Zeroizing::new(secret.to_owned()));
    }
    let mut key = secret;
    while key
        .get(..7)
        .is_some_and(|p| p.eq_ignore_ascii_case("Bearer "))
    {
        key = &key[7..];
    }
    if key.is_empty() {
        return Err(Error::new("KEY_VALUE", "Bearer 前缀后须有密钥。"));
    }
    Ok(Zeroizing::new(format!("Bearer {key}")))
}

pub(crate) enum Kind {
    Object(BTreeMap<String, Node>),
    Array(Vec<Node>),
    String(Zeroizing<String>),
    Scalar(Value),
}
pub(crate) struct Node {
    pub start: usize,
    pub end: usize,
    pub kind: Kind,
}
impl Node {
    pub fn resolve(&self, pointer: &str) -> Result<&Node> {
        let mut node = self;
        for segment in segments(pointer)? {
            node = match &node.kind {
                Kind::Object(properties) => properties.get(&segment),
                Kind::Array(items) => segment
                    .parse::<usize>()
                    .ok()
                    .filter(|v| v.to_string() == segment)
                    .and_then(|i| items.get(i)),
                _ => None,
            }
            .ok_or(Error::new(
                "FIELD_MISSING",
                "精确字段不存在；不自动创建字段或父路径。",
            ))?;
        }
        Ok(node)
    }
    pub fn value(&self) -> Value {
        match &self.kind {
            Kind::Object(props) => {
                Value::Object(props.iter().map(|(k, v)| (k.clone(), v.value())).collect())
            }
            Kind::Array(items) => Value::Array(items.iter().map(Node::value).collect()),
            Kind::String(value) => Value::String(value.to_string()),
            Kind::Scalar(value) => value.clone(),
        }
    }
}
struct Parser<'a> {
    text: &'a str,
    offset: usize,
    nodes: usize,
}
impl<'a> Parser<'a> {
    fn invalid() -> Error {
        Error::new("JSON_INVALID", "JSON/JSONC 结构无效，拒绝修改。")
    }
    fn skip(&mut self) -> Result<()> {
        let bytes = self.text.as_bytes();
        while self.offset < bytes.len() {
            match bytes[self.offset] {
                b' ' | b'\t' | b'\r' | b'\n' => self.offset += 1,
                b'/' if bytes.get(self.offset + 1) == Some(&b'/') => {
                    self.offset += 2;
                    while self.offset < bytes.len() && !matches!(bytes[self.offset], b'\r' | b'\n')
                    {
                        self.offset += 1;
                    }
                }
                b'/' if bytes.get(self.offset + 1) == Some(&b'*') => {
                    let end = self.text[self.offset + 2..]
                        .find("*/")
                        .ok_or(Self::invalid())?;
                    self.offset += end + 4;
                }
                _ => break,
            }
        }
        Ok(())
    }
    fn take(&mut self, byte: u8) -> bool {
        if self.text.as_bytes().get(self.offset) == Some(&byte) {
            self.offset += 1;
            true
        } else {
            false
        }
    }
    fn string(&mut self) -> Result<Zeroizing<String>> {
        let start = self.offset;
        if !self.take(b'"') {
            return Err(Self::invalid());
        }
        let bytes = self.text.as_bytes();
        // An escape-free body already passed every rule the scanner enforces
        // (no control bytes, UTF-8 text), so its content is exactly the scanned
        // bytes; only escaped bodies need serde_json to decode the escapes.
        let mut escaped = false;
        while self.offset < bytes.len() {
            let byte = bytes[self.offset];
            self.offset += 1;
            if byte < 0x20 {
                return Err(Self::invalid());
            }
            if byte == b'"' {
                return if escaped {
                    serde_json::from_str(&self.text[start..self.offset])
                        .map(Zeroizing::new)
                        .map_err(|_| Self::invalid())
                } else {
                    Ok(Zeroizing::new(
                        self.text[start + 1..self.offset - 1].to_owned(),
                    ))
                };
            }
            if byte == b'\\' {
                escaped = true;
                let escape = *bytes.get(self.offset).ok_or(Self::invalid())?;
                self.offset += 1;
                if escape == b'u' {
                    for _ in 0..4 {
                        if !bytes.get(self.offset).is_some_and(u8::is_ascii_hexdigit) {
                            return Err(Self::invalid());
                        }
                        self.offset += 1;
                    }
                } else if !matches!(
                    escape,
                    b'"' | b'\\' | b'/' | b'b' | b'f' | b'n' | b'r' | b't'
                ) {
                    return Err(Self::invalid());
                }
            }
        }
        Err(Self::invalid())
    }
    fn node(&mut self, depth: usize) -> Result<Node> {
        self.nodes += 1;
        if depth > 64 || self.nodes > 100000 {
            return Err(Error::new("JSON_LIMIT", "JSON 深度或节点数量超出上限。"));
        }
        self.skip()?;
        let start = self.offset;
        let kind = match self
            .text
            .as_bytes()
            .get(self.offset)
            .copied()
            .ok_or(Self::invalid())?
        {
            b'{' => {
                self.offset += 1;
                self.skip()?;
                let mut properties = BTreeMap::new();
                if !self.take(b'}') {
                    loop {
                        self.skip()?;
                        let name = self.string()?.to_string();
                        self.skip()?;
                        if !self.take(b':') {
                            return Err(Self::invalid());
                        }
                        let child = self.node(depth + 1)?;
                        if properties.insert(name, child).is_some() {
                            return Err(Error::new(
                                "JSON_DUPLICATE",
                                "字段名称重复或转义后同名，整文件拒绝修改。",
                            ));
                        }
                        self.skip()?;
                        if self.take(b'}') {
                            break;
                        }
                        if !self.take(b',') {
                            return Err(Self::invalid());
                        }
                        self.skip()?;
                        if self.take(b'}') {
                            break;
                        }
                    }
                }
                Kind::Object(properties)
            }
            b'[' => {
                self.offset += 1;
                self.skip()?;
                let mut items = Vec::new();
                if !self.take(b']') {
                    loop {
                        items.push(self.node(depth + 1)?);
                        self.skip()?;
                        if self.take(b']') {
                            break;
                        }
                        if !self.take(b',') {
                            return Err(Self::invalid());
                        }
                        self.skip()?;
                        if self.take(b']') {
                            break;
                        }
                    }
                }
                Kind::Array(items)
            }
            b'"' => Kind::String(self.string()?),
            _ => {
                while let Some(byte) = self.text.as_bytes().get(self.offset) {
                    if matches!(
                        byte,
                        b' ' | b'\t' | b'\r' | b'\n' | b',' | b']' | b'}' | b'/'
                    ) {
                        break;
                    }
                    self.offset += 1;
                }
                if self.offset == start {
                    return Err(Self::invalid());
                }
                let value: Value = serde_json::from_str(&self.text[start..self.offset])
                    .map_err(|_| Self::invalid())?;
                if !matches!(value, Value::Number(_) | Value::Bool(_) | Value::Null) {
                    return Err(Self::invalid());
                }
                Kind::Scalar(value)
            }
        };
        Ok(Node {
            start,
            end: self.offset,
            kind,
        })
    }
}

#[derive(Clone, Copy)]
enum Encoding {
    Utf8,
    Utf16Le,
    Utf16Be,
}
pub(crate) struct Document {
    text: Zeroizing<String>,
    encoding: Encoding,
    bom: usize,
    pub root: Node,
}
impl Document {
    pub fn parse(bytes: &[u8]) -> Result<Self> {
        if bytes.len() > MAX_CONFIG_BYTES {
            return Err(Error::new("CONFIG_SIZE", "配置文件超过 16 MiB，拒绝处理。"));
        }
        if bytes.starts_with(&[0xff, 0xfe, 0, 0]) || bytes.starts_with(&[0, 0, 0xfe, 0xff]) {
            return Err(Error::new("ENCODING_UNSUPPORTED", "不支持 UTF-32。"));
        }
        let (encoding, bom) = if bytes.starts_with(&[0xef, 0xbb, 0xbf]) {
            (Encoding::Utf8, 3)
        } else if bytes.starts_with(&[0xff, 0xfe]) {
            (Encoding::Utf16Le, 2)
        } else if bytes.starts_with(&[0xfe, 0xff]) {
            (Encoding::Utf16Be, 2)
        } else {
            (Encoding::Utf8, 0)
        };
        let invalid = || {
            Error::new(
                "ENCODING_INVALID",
                "仅支持严格 UTF-8 和带 BOM 的 UTF-16 LE/BE。",
            )
        };
        let body = &bytes[bom..];
        let text = match encoding {
            Encoding::Utf8 => std::str::from_utf8(body)
                .map(str::to_owned)
                .map_err(|_| invalid())?,
            _ => {
                let (pairs, remainder) = body.as_chunks::<2>();
                if !remainder.is_empty() {
                    return Err(invalid());
                }
                let units = Zeroizing::new(
                    pairs
                        .iter()
                        .map(|v| match encoding {
                            Encoding::Utf16Le => u16::from_le_bytes(*v),
                            _ => u16::from_be_bytes(*v),
                        })
                        .collect::<Vec<u16>>(),
                );
                String::from_utf16(&units).map_err(|_| invalid())?
            }
        };
        let text = Zeroizing::new(text);
        let mut parser = Parser {
            text: &text,
            offset: 0,
            nodes: 0,
        };
        let root = parser.node(0)?;
        parser.skip()?;
        if parser.offset != text.len() || !matches!(root.kind, Kind::Object(_) | Kind::Array(_)) {
            return Err(Parser::invalid());
        }
        Ok(Self {
            text,
            encoding,
            bom,
            root,
        })
    }
    fn encode(&self, text: &str) -> Zeroizing<Vec<u8>> {
        Zeroizing::new(match self.encoding {
            Encoding::Utf8 => text.as_bytes().to_vec(),
            Encoding::Utf16Le => text.encode_utf16().flat_map(u16::to_le_bytes).collect(),
            Encoding::Utf16Be => text.encode_utf16().flat_map(u16::to_be_bytes).collect(),
        })
    }
    pub fn encoding_name(&self) -> String {
        let name = match self.encoding {
            Encoding::Utf8 => "UTF-8",
            Encoding::Utf16Le => "UTF-16 LE",
            Encoding::Utf16Be => "UTF-16 BE",
        };
        format!(
            "{name}（{}）",
            if self.bom == 0 {
                "无 BOM"
            } else {
                "保留 BOM"
            }
        )
    }
    fn byte_count(&self, text: &str) -> usize {
        match self.encoding {
            Encoding::Utf8 => text.len(),
            Encoding::Utf16Le | Encoding::Utf16Be => text.encode_utf16().count() * 2,
        }
    }
    pub fn patch(
        &self,
        original: &[u8],
        patches: &[(usize, usize, Zeroizing<String>)],
    ) -> Result<Zeroizing<Vec<u8>>> {
        // Calculate the final bound before allocation. Walk text gaps only once,
        // rather than repeatedly encoding prefixes containing unrelated secrets.
        let mut length = original.len();
        for (start, end, token) in patches {
            length = length
                .checked_sub(self.byte_count(&self.text[*start..*end]))
                .and_then(|n| n.checked_add(self.byte_count(token)))
                .ok_or(Error::new("CONFIG_SIZE", "配置文件超过安全上限。"))?;
        }
        if length > MAX_CONFIG_BYTES {
            return Err(Error::new(
                "CONFIG_SIZE",
                "更新后的配置文件超过 16 MiB，拒绝处理。",
            ));
        }
        let mut output = Zeroizing::new(Vec::with_capacity(length));
        let mut byte_cursor = self.bom;
        let mut text_cursor = 0;
        output.extend_from_slice(&original[..self.bom]);
        for (start, end, token) in patches {
            let offset = byte_cursor + self.byte_count(&self.text[text_cursor..*start]);
            let limit = offset + self.byte_count(&self.text[*start..*end]);
            output.extend_from_slice(&original[byte_cursor..offset]);
            output.extend_from_slice(&self.encode(token));
            byte_cursor = limit;
            text_cursor = *end;
        }
        output.extend_from_slice(&original[byte_cursor..]);
        Ok(output)
    }
}

pub struct EditRequest {
    pub label: String,
    pub pointer: String,
    pub secret: Zeroizing<String>,
    pub bearer: bool,
    pub replace_variables: bool,
}
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FieldView {
    pub label: String,
    pub pointer: String,
    pub before: String,
    pub after: String,
    pub status: &'static str,
}
pub struct EditResult {
    pub bytes: Zeroizing<Vec<u8>>,
    pub fields: Vec<FieldView>,
    pub encoding: String,
}

/// Internal-consumer convenience parser. The returned Value contains plaintext;
/// never serialize it into previews, IPC responses, logs, or error messages.
pub fn parse_value(original: &[u8]) -> Result<Value> {
    Ok(Document::parse(original)?.root.value())
}

pub fn edit(original: &[u8], requests: &[EditRequest]) -> Result<EditResult> {
    if requests.len() > 500 {
        return Err(Error::new("TARGET_LIMIT", "单次最多处理 500 个字段。"));
    }
    let document = Document::parse(original)?;
    let mut seen = BTreeSet::new();
    let mut patches = Vec::new();
    let mut fields = Vec::new();
    for request in requests {
        let node = document.root.resolve(&request.pointer)?;
        let Kind::String(old) = &node.kind else {
            return Err(Error::new("FIELD_TYPE", "密钥目标必须是现有字符串值。"));
        };
        if !seen.insert(node.start) {
            return Err(Error::new(
                "FIELD_AMBIGUOUS",
                "同一文件字段重复选择，拒绝整文件写入。",
            ));
        }
        let protected = has_variable(old) && !request.replace_variables;
        // Protected values never need a replacement, including malformed legacy
        // keys. They must remain a successful, byte-identical preservation.
        let value = if protected {
            Zeroizing::new(String::new())
        } else {
            bearer_value(&request.secret, request.bearer)?
        };
        let status = if protected {
            "保留变量引用"
        } else if old.as_str() == value.as_str() {
            "无需修改"
        } else if has_variable(old) {
            "将明确替换变量"
        } else {
            "准备写入"
        };
        fields.push(FieldView {
            label: request.label.clone(),
            pointer: request.pointer.clone(),
            before: if protected {
                "变量引用（已遮罩）".to_owned()
            } else if old.is_empty() {
                "（空值）".to_owned()
            } else if old
                .get(..7)
                .is_some_and(|p| p.eq_ignore_ascii_case("Bearer "))
            {
                format!("Bearer {MASK}")
            } else {
                MASK.to_owned()
            },
            after: if protected {
                "保留原引用".to_owned()
            } else if request.bearer {
                format!("Bearer {MASK}")
            } else {
                MASK.to_owned()
            },
            status,
        });
        if !protected && old.as_str() != value.as_str() {
            let token = serde_json::to_string(value.as_str())
                .map_err(|_| Error::new("JSON_VALUE", "无法编码字段值。"))?;
            patches.push((node.start, node.end, Zeroizing::new(token)));
        }
    }
    patches.sort_by_key(|p| p.0);
    Ok(EditResult {
        bytes: document.patch(original, &patches)?,
        fields,
        encoding: document.encoding_name(),
    })
}

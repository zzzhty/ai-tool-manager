use serde::Serialize;
use std::{fmt, io};

#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Error {
    pub code: &'static str,
    pub message: &'static str,
}

pub type Result<T> = std::result::Result<T, Error>;

impl Error {
    pub const fn new(code: &'static str, message: &'static str) -> Self {
        Self { code, message }
    }
    pub fn io(error: io::Error) -> Self {
        match error.kind() {
            io::ErrorKind::PermissionDenied => Self::new("ACCESS_DENIED", "权限不足或文件只读。"),
            io::ErrorKind::NotFound => {
                Self::new("FILE_MISSING", "文件已移除或路径失效，请重新预览。")
            }
            _ => Self::new("FILE_IO", "文件访问失败：可能被占用或存储空间不足。"),
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}
impl std::error::Error for Error {}
impl From<io::Error> for Error {
    fn from(value: io::Error) -> Self {
        Self::io(value)
    }
}

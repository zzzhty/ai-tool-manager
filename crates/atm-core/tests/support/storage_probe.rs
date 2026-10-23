//! Negative storage diagnostic. Creates no entry and never prints native errors or secrets.
fn main() {
    #[cfg(target_os = "linux")]
    match atm_core::linux::crypt(b"TEST_ONLY_PROBE", true) {
        Err(error) => println!("{}", error.code),
        Ok(_) => std::process::exit(2),
    }
    #[cfg(not(target_os = "linux"))]
    println!("PLATFORM_UNSUPPORTED");
}

//! Starts solana-core as a child process and learns its port and token.
//!
//! The core prints `SOLANA_CORE_READY {"port": .., "token": ".."}` to stdout once it listens.
//! In debug builds the core runs from source through `uv run`; WP13 adds the bundled sidecar.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager};

const READY_PREFIX: &str = "SOLANA_CORE_READY ";

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CoreInfo {
    pub port: u16,
    pub token: String,
}

#[derive(Default)]
pub struct CoreState {
    pub info: Mutex<Option<CoreInfo>>,
    pub child: Mutex<Option<Child>>,
}

fn random_token() -> String {
    let mut bytes = [0u8; 24];
    getrandom::fill(&mut bytes).expect("OS random generator is unavailable");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Fake mode is on by default in dev until the real voice pipeline lands (WP6).
/// `SOLANA_FAKE=0 pnpm tauri dev` starts the real core.
fn fake_mode() -> bool {
    std::env::var("SOLANA_FAKE")
        .map(|v| v != "0")
        .unwrap_or(cfg!(debug_assertions))
}

fn core_command(token: &str) -> Command {
    let mut cmd = if cfg!(debug_assertions) {
        let core_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../core");
        let mut c = Command::new("uv");
        c.arg("run")
            .arg("--project")
            .arg(core_dir)
            .arg("solana-core");
        c
    } else {
        // WP13 replaces this with the PyInstaller/Nuitka sidecar shipped in the bundle.
        Command::new("solana-core")
    };
    cmd.args(["--port", "0", "--token", token]);
    if fake_mode() {
        cmd.arg("--fake");
    }
    cmd
}

pub fn spawn(app: &AppHandle) -> std::io::Result<()> {
    let token = random_token();
    let mut child = core_command(&token)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()?;
    let stdout = child.stdout.take().expect("stdout is piped");
    *app.state::<CoreState>().child.lock().unwrap() = Some(child);

    let app = app.clone();
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            match line.strip_prefix(READY_PREFIX) {
                Some(json) => match serde_json::from_str::<CoreInfo>(json) {
                    Ok(info) => {
                        *app.state::<CoreState>().info.lock().unwrap() = Some(info.clone());
                        let _ = app.emit("core-ready", info);
                    }
                    Err(err) => eprintln!("solana-core: bad ready line: {err}"),
                },
                None => println!("[core] {line}"),
            }
        }
        *app.state::<CoreState>().info.lock().unwrap() = None;
        let _ = app.emit("core-exited", ());
    });
    Ok(())
}

pub fn kill(app: &AppHandle) {
    if let Some(mut child) = app.state::<CoreState>().child.lock().unwrap().take() {
        // `uv run` on Windows does not pass the kill on to the Python child: kill the tree.
        #[cfg(windows)]
        let _ = Command::new("taskkill")
            .args(["/pid", &child.id().to_string(), "/t", "/f"])
            .status();
        let _ = child.kill();
        let _ = child.wait();
    }
}

/// Port and token of the running core, or null while it is starting.
#[tauri::command]
pub fn core_info(state: tauri::State<'_, CoreState>) -> Option<CoreInfo> {
    state.info.lock().unwrap().clone()
}

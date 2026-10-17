use serde_json::{json, Value};
use std::{
    env,
    ffi::OsString,
    fs,
    io::Read,
    path::{Component, Path, PathBuf},
    process::{self, Command},
};

type Result<T> = std::result::Result<T, &'static str>;

#[cfg(windows)]
mod windows_private;

fn compiled_target() -> &'static str {
    match (env::consts::OS, env::consts::ARCH) {
        ("macos", "aarch64") => "macos-arm64",
        ("macos", "x86_64") => "macos-x64",
        ("linux", "x86_64") => "linux-x64",
        ("windows", "x86_64") => "windows-x64",
        _ => "unsupported",
    }
}

fn unsafe_metadata(metadata: &fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        metadata.file_type().is_symlink() || metadata.file_attributes() & 0x400 != 0
    }
    #[cfg(not(windows))]
    {
        metadata.file_type().is_symlink()
    }
}

fn directory(path: &Path) -> Result<()> {
    let metadata = fs::symlink_metadata(path).map_err(|_| "runtime directory is missing")?;
    if unsafe_metadata(&metadata) || !metadata.is_dir() {
        return Err("runtime directory is unsafe");
    }
    Ok(())
}

fn private_path(path: &Path, forbidden_permissions: u32) -> Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        extern "C" {
            fn geteuid() -> u32;
        }
        let metadata = fs::symlink_metadata(path).map_err(|_| "private runtime path is missing")?;
        if metadata.uid() != unsafe { geteuid() } || metadata.mode() & forbidden_permissions != 0 {
            return Err("runtime path is not private to the current user");
        }
    }
    #[cfg(windows)]
    {
        let _ = forbidden_permissions;
        windows_private::check(path)?;
    }
    #[cfg(not(any(unix, windows)))]
    let _ = (path, forbidden_permissions);
    Ok(())
}

fn binding_configuration(path: &Path) -> Result<Value> {
    private_path(path, 0o022)?;
    configuration(path)
}

fn configuration(path: &Path) -> Result<Value> {
    let metadata = fs::symlink_metadata(path).map_err(|_| "runtime binding is not prepared")?;
    if unsafe_metadata(&metadata) || !metadata.is_file() || metadata.len() > 131072 {
        return Err("runtime configuration is unsafe or oversized");
    }
    let file = fs::File::open(path).map_err(|_| "runtime configuration cannot be opened")?;
    let mut bytes = Vec::new();
    file.take(131073)
        .read_to_end(&mut bytes)
        .map_err(|_| "runtime configuration cannot be read")?;
    if bytes.len() > 131072 {
        return Err("runtime configuration is oversized");
    }
    serde_json::from_slice(&bytes).map_err(|_| "runtime configuration is invalid JSON")
}

fn field<'a>(value: &'a Value, name: &str) -> Result<&'a str> {
    value
        .get(name)
        .and_then(Value::as_str)
        .filter(|text| !text.is_empty())
        .ok_or("runtime configuration has a missing or invalid field")
}

fn digest_key(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn absolute_path(value: &Value, name: &str) -> Result<PathBuf> {
    let path = PathBuf::from(field(value, name)?);
    if !path.is_absolute() || path.components().any(|part| part == Component::ParentDir) {
        return Err("runtime binding requires absolute paths without parent traversal");
    }
    Ok(path)
}

fn data_home() -> Result<PathBuf> {
    if let Some(value) = env::var_os("ENGINEERING_ASSISTANT_DATA_HOME") {
        let path = PathBuf::from(value);
        if !path.is_absolute() {
            return Err("runtime data home must be absolute");
        }
        return Ok(path);
    }
    #[cfg(windows)]
    {
        env::var_os("LOCALAPPDATA")
            .map(|path| PathBuf::from(path).join("engineering-assistant"))
            .ok_or("runtime data home is unavailable")
    }
    #[cfg(not(windows))]
    {
        if env::consts::OS == "linux" {
            if let Some(value) = env::var_os("XDG_DATA_HOME") {
                let path = PathBuf::from(value);
                if path.is_absolute() {
                    return Ok(path.join("engineering-assistant"));
                }
            }
        }
        let home = env::var_os("HOME")
            .map(PathBuf::from)
            .ok_or("runtime user home is unavailable")?;
        if !home.is_absolute() {
            return Err("runtime user home must be absolute");
        }
        Ok(home.join(if env::consts::OS == "macos" {
            "Library/Application Support/engineering-assistant"
        } else {
            ".local/share/engineering-assistant"
        }))
    }
}

fn runtime_command(arguments: &[OsString]) -> Result<Command> {
    let executable = env::current_exe().map_err(|_| "native launcher location is unavailable")?;
    let root = executable
        .parent()
        .and_then(Path::parent)
        .ok_or("native launcher layout is invalid")?;
    directory(root)?;
    directory(
        executable
            .parent()
            .ok_or("native launcher layout is invalid")?,
    )?;
    let lock = configuration(&root.join("runtime-lock.json"))?;
    let schema = field(&lock, "schema_version")?;
    if !["1", "2"].contains(&schema) {
        return Err("plugin runtime schema is unsupported");
    }
    if field(&lock, "target")? != compiled_target() {
        return Err("plugin target does not match the native launcher");
    }
    let agent = field(&lock, "agent")?;
    if !["codex", "hermes", "claude-code"].contains(&agent) {
        return Err("plugin agent is unsupported");
    }
    field(&lock, "canonical_version")?;
    let key = field(&lock, "environment_key")?;
    if !digest_key(key) {
        return Err("plugin environment key is invalid");
    }
    let data = data_home()?;
    directory(&data)?;
    private_path(&data, 0o077)?;
    let bindings = data.join("bindings");
    directory(&bindings)?;
    private_path(&bindings, 0o022)?;
    let agent_bindings = bindings.join(agent);
    match fs::symlink_metadata(&agent_bindings) {
        Ok(_) => {
            directory(&agent_bindings)?;
            private_path(&agent_bindings, 0o022)?;
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err("versioned runtime directory cannot be inspected"),
    }
    let versioned = agent_bindings.join(format!("{key}.json"));
    // Keep old bindings usable while a newer release changes the latest alias.
    let binding = match fs::symlink_metadata(&versioned) {
        Ok(_) => {
            directory(&bindings.join(agent))?;
            binding_configuration(&versioned)?
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            binding_configuration(&bindings.join(format!("{agent}.json")))?
        }
        Err(_) => return Err("versioned runtime binding cannot be inspected"),
    };
    for name in ["schema_version", "agent", "target", "environment_key"] {
        if field(&binding, name)? != field(&lock, name)? {
            return Err("runtime binding does not match this plugin release");
        }
    }
    if schema == "2" {
        let digest = field(&lock, "python_artifact_digest")?;
        let artifact = lock
            .get("python_artifact")
            .ok_or("plugin Python artifact is missing")?;
        if !digest_key(digest)
            || field(&binding, "python_artifact_digest")? != digest
            || field(&binding, "python_build")? != field(artifact, "build")?
        {
            return Err("runtime binding does not match the Python artifact");
        }
        let base = absolute_path(&binding, "python_base")?;
        let parent = base
            .parent()
            .ok_or("prepared Python artifact base has no parent")?;
        directory(parent)?;
        private_path(parent, 0o022)?;
        directory(&base)?;
        private_path(&base, 0o022)?;
        let name = field(artifact, "key")?.replace("-darwin-", "-macos-");
        if parent.file_name().and_then(|part| part.to_str()) != Some(digest)
            || base.file_name().and_then(|part| part.to_str()) != Some(name.as_str())
        {
            return Err("prepared Python base differs from its artifact");
        }
    }
    let environment = absolute_path(&binding, "environment")?;
    directory(&environment)?;
    private_path(&environment, 0o022)?;
    let python = absolute_path(&binding, "python")?;
    let python_parent = python
        .parent()
        .ok_or("runtime interpreter path is invalid")?;
    let expected_parent = environment.join(if cfg!(windows) { "Scripts" } else { "bin" });
    if python_parent != expected_parent {
        return Err("runtime interpreter is outside its environment");
    }
    directory(python_parent)?;
    private_path(python_parent, 0o022)?;
    // A venv interpreter is commonly a symlink to the managed base Python.
    // Preserve its literal path so Python still discovers the venv correctly.
    if !python.is_file() {
        return Err("prepared runtime interpreter is missing");
    }
    #[cfg(windows)]
    private_path(&python, 0o022)?;
    let boot = root.join("runtime_boot.py");
    let metadata = fs::symlink_metadata(&boot).map_err(|_| "runtime bootstrap is missing")?;
    if unsafe_metadata(&metadata) || !metadata.is_file() {
        return Err("runtime bootstrap is unsafe");
    }
    let mut command = Command::new(python);
    command
        .arg("-I")
        .arg("-B")
        .arg("-X")
        .arg("utf8")
        .arg(boot)
        .args(arguments);
    Ok(command)
}

#[cfg(unix)]
fn launch(mut command: Command) -> Result<i32> {
    use std::os::unix::process::CommandExt;
    let _error = command.exec();
    Err("prepared runtime interpreter cannot be started")
}

#[cfg(windows)]
mod windows_job {
    use super::{Command, Result};
    use std::{
        ffi::c_void,
        mem,
        os::windows::{io::AsRawHandle, process::CommandExt},
        ptr,
    };

    type Handle = *mut c_void;
    #[repr(C)]
    struct BasicLimits {
        process_time: i64,
        job_time: i64,
        flags: u32,
        min_working_set: usize,
        max_working_set: usize,
        active_processes: u32,
        affinity: usize,
        priority: u32,
        scheduling: u32,
    }
    #[repr(C)]
    struct ExtendedLimits {
        basic: BasicLimits,
        io: [u64; 6],
        process_memory: usize,
        job_memory: usize,
        peak_process_memory: usize,
        peak_job_memory: usize,
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn CreateJobObjectW(attributes: *const c_void, name: *const u16) -> Handle;
        fn SetInformationJobObject(job: Handle, class: i32, info: *const c_void, size: u32) -> i32;
        fn AssignProcessToJobObject(job: Handle, process: Handle) -> i32;
        fn CloseHandle(handle: Handle) -> i32;
    }
    struct Job(Handle);
    impl Drop for Job {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }

    pub fn launch(mut command: Command) -> Result<i32> {
        let job = Job(unsafe { CreateJobObjectW(ptr::null(), ptr::null()) });
        if job.0.is_null() {
            return Err("runtime process Job Object cannot be created");
        }
        let mut limits: ExtendedLimits = unsafe { mem::zeroed() };
        limits.basic.flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if unsafe {
            SetInformationJobObject(
                job.0,
                9,
                &limits as *const _ as *const c_void,
                mem::size_of::<ExtendedLimits>() as u32,
            )
        } == 0
        {
            return Err("runtime process Job Object cannot be configured");
        }
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW for GUI-hosted MCP and hooks.
        let mut child = command
            .spawn()
            .map_err(|_| "prepared runtime interpreter cannot be started")?;
        if unsafe { AssignProcessToJobObject(job.0, child.as_raw_handle()) } == 0 {
            let killed = child.kill();
            let waited = child.wait();
            if killed.is_err() || waited.is_err() {
                return Err("runtime process cleanup could not be confirmed");
            }
            return Err("runtime process cannot join its Job Object");
        }
        child
            .wait()
            .map(|status| status.code().unwrap_or(1))
            .map_err(|_| "runtime process wait failed")
    }
}

#[cfg(windows)]
use windows_job::launch;

fn main() {
    let arguments: Vec<OsString> = env::args_os().skip(1).collect();
    if arguments
        .first()
        .is_some_and(|argument| argument == "--launcher-info")
    {
        println!(
            "{}",
            json!({"schema_version": "1", "launcher_version": "1", "target": compiled_target(), "source_digest": env!("EA_LAUNCHER_SOURCE_DIGEST")})
        );
        return;
    }
    let hook = arguments.first().is_some_and(|argument| argument == "hook");
    match runtime_command(&arguments).and_then(launch) {
        Ok(status) => process::exit(status),
        Err(reason) => {
            eprintln!(
                "{}",
                json!({"status": "needs_preparation", "reason": reason})
            );
            if hook {
                println!("{{}}");
            } else {
                process::exit(2);
            }
        }
    }
}

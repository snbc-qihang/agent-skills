// CI-only fixed entry: no Python/CRT startup, argv/environment or user payload.
#![no_std]
#![no_main]

use core::{ffi::c_void, mem::MaybeUninit, ptr};

#[link(name = "kernel32")]
extern "system" {
    fn GetStdHandle(kind: u32) -> *mut c_void;
    fn WriteFile(handle: *mut c_void, data: *const u8, length: u32,
                 written: *mut u32, overlapped: *mut c_void) -> i32;
    fn LoadLibraryExW(name: *const u16, reserved: *mut c_void, flags: u32) -> *mut c_void;
    fn GetLastError() -> u32;
    fn FreeLibrary(module: *mut c_void) -> i32;
    fn GetModuleFileNameW(module: *mut c_void, name: *mut u16, capacity: u32) -> u32;
    fn CreateFileW(name: *const u16, access: u32, sharing: u32, attributes: *mut c_void,
                   creation: u32, flags: u32, template: *mut c_void) -> *mut c_void;
    fn CreateFileMappingW(file: *mut c_void, attributes: *mut c_void, protection: u32,
                          high: u32, low: u32, name: *const u16) -> *mut c_void;
    fn CloseHandle(handle: *mut c_void) -> i32;
    fn ExitProcess(code: u32) -> !;
}

#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! {
    unsafe { ExitProcess(77) }
}

const fn wide<const N: usize>(text: &[u8; N]) -> [u16; N] {
    let mut result = [0; N];
    let mut index = 0;
    while index < N {
        result[index] = text[index] as u16;
        index += 1;
    }
    result
}

unsafe fn write(handle: *mut c_void, text: &[u8]) {
    let mut offset = 0;
    while offset < text.len() {
        let mut written = 0;
        let remaining = (text.len() - offset) as u32;
        if WriteFile(handle, text.as_ptr().add(offset), remaining, &mut written, ptr::null_mut()) == 0
            || written == 0 || written > remaining {
            ExitProcess(71);
        }
        offset += written as usize;
    }
}

unsafe fn load(handle: *mut c_void, label: &[u8], name: *const u16, flags: u32) {
    write(handle, b"LOAD ");
    write(handle, label);
    write(handle, b"\n");
    let module = LoadLibraryExW(name, ptr::null_mut(), flags);
    let error = if module.is_null() { GetLastError() } else { 0 };
    write(handle, b"RESULT ");
    write(handle, label);
    write(handle, b" ");
    status(handle, error);
    if !module.is_null() && FreeLibrary(module) == 0 {
        ExitProcess(73);
    }
}

unsafe fn status(handle: *mut c_void, error: u32) {
    let digits = b"0123456789ABCDEF";
    let mut status = *b"0x00000000\n";
    let mut index = 0;
    while index < 8 {
        status[index + 2] = digits[((error >> (28 - index * 4)) & 15) as usize];
        index += 1;
    }
    write(handle, &status);
}

unsafe fn private_name(name: *mut u16, suffix: &[u8]) {
    // GetModuleFileNameW identifies this owned executable, never argv/CWD/PATH.
    let length = GetModuleFileNameW(ptr::null_mut(), name, 1024) as usize;
    if length < 3 || length >= 1024 || ptr::read(name.add(1)) != b':' as u16
        || ptr::read(name.add(2)) != b'\\' as u16 {
        ExitProcess(72);
    }
    let mut start = length;
    while start > 0 && ptr::read(name.add(start - 1)) != b'\\' as u16 {
        start -= 1;
    }
    if start < 3 || start + suffix.len() > 1024 {
        ExitProcess(72);
    }
    let mut index = 0;
    while index < suffix.len() {
        ptr::write(name.add(start + index), suffix[index] as u16);
        index += 1;
    }
}

unsafe fn private_load(handle: *mut c_void, label: &[u8], suffix: &[u8]) {
    // No initialization of the large stack buffer or implicit CRT memset.
    let mut storage = MaybeUninit::<[u16; 1024]>::uninit();
    let name = storage.as_mut_ptr().cast::<u16>();
    private_name(name, suffix);
    // DLL_LOAD_DIR|SYSTEM32 requires an absolute path and runs real DllMain.
    // https://learn.microsoft.com/windows/win32/api/libloaderapi/nf-libloaderapi-loadlibraryexw
    load(handle, label, name, 0x900);
}

unsafe fn check_begin(handle: *mut c_void, operation: &[u8]) {
    write(handle, b"CHECK ");
    write(handle, operation);
    write(handle, b" python313.dll\n");
}

unsafe fn check_result(handle: *mut c_void, operation: &[u8], error: Option<u32>) {
    write(handle, b"CHECK_RESULT ");
    write(handle, operation);
    write(handle, b" python313.dll ");
    match error {
        Some(value) => status(handle, value),
        None => write(handle, b"SKIPPED\n"),
    }
}

unsafe fn image_check(handle: *mut c_void, file: *mut c_void, operation: &[u8], protection: u32) {
    check_begin(handle, operation);
    if file as isize == -1 {
        check_result(handle, operation, None);
        return;
    }
    // Read-only, unnamed, whole-file object. No MapViewOfFile or DLL entry.
    // SEC_IMAGE must include a page protection; SEC_IMAGE_NO_EXECUTE requires PAGE_READONLY.
    // https://learn.microsoft.com/windows/win32/api/memoryapi/nf-memoryapi-createfilemappingw
    let image = CreateFileMappingW(file, ptr::null_mut(), protection, 0, 0, ptr::null());
    let error = if image.is_null() { GetLastError() } else { 0 };
    check_result(handle, operation, Some(error));
    if !image.is_null() && CloseHandle(image) == 0 {
        ExitProcess(74);
    }
}

unsafe fn private_checks(handle: *mut c_void) {
    let mut storage = MaybeUninit::<[u16; 1024]>::uninit();
    let name = storage.as_mut_ptr().cast::<u16>();
    private_name(name, b"python313.dll\0");
    check_begin(handle, b"file_read");
    // GENERIC_READ, sharing read/write/delete, OPEN_EXISTING, normal attributes;
    // no writes, creation, inherited handles, registry, argv, CWD or PATH input.
    // https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-createfilew
    let file = CreateFileW(name, 0x80000000, 7, ptr::null_mut(), 3, 0x80, ptr::null_mut());
    let error = if file as isize == -1 { GetLastError() } else { 0 };
    check_result(handle, b"file_read", Some(error));
    // Separate read/execute request makes an executable image access denial
    // observable before CreateFileMapping; it still never maps or executes code.
    check_begin(handle, b"file_read_execute");
    let executable = CreateFileW(name, 0xA0000000, 7, ptr::null_mut(), 3, 0x80, ptr::null_mut());
    let error = if executable as isize == -1 { GetLastError() } else { 0 };
    check_result(handle, b"file_read_execute", Some(error));
    image_check(handle, executable, b"sec_image", 0x01000002);
    image_check(handle, file, b"sec_image_no_execute", 0x11000002);
    if executable as isize != -1 && CloseHandle(executable) == 0 {
        ExitProcess(74);
    }
    if file as isize != -1 && CloseHandle(file) == 0 {
        ExitProcess(74);
    }
}

#[no_mangle]
pub unsafe extern "system" fn probe_entry() -> ! {
    let handle = GetStdHandle(-11_i32 as u32);
    if handle.is_null() || handle as isize == -1 {
        ExitProcess(70);
    }
    write(handle, b"EA_NATIVE_DLL_PROBE_V2\n");
    private_checks(handle);
    // Fixed sequential observations; loaded-module state is not independent.
    load(handle, b"ucrtbase.dll", wide(b"ucrtbase.dll\0").as_ptr(), 0x800);
    load(handle, b"advapi32.dll", wide(b"advapi32.dll\0").as_ptr(), 0x800);
    load(handle, b"shell32.dll", wide(b"shell32.dll\0").as_ptr(), 0x800);
    load(handle, b"ole32.dll", wide(b"ole32.dll\0").as_ptr(), 0x800);
    load(handle, b"oleaut32.dll", wide(b"oleaut32.dll\0").as_ptr(), 0x800);
    // CPython v3.13.13 core imports verified in fixed PBS build 20260414.
    // pathcch.lib resolves to this API-set name in the actual PE.
    load(handle, b"version.dll", wide(b"version.dll\0").as_ptr(), 0x800);
    load(handle, b"ws2_32.dll", wide(b"ws2_32.dll\0").as_ptr(), 0x800);
    load(handle, b"bcrypt.dll", wide(b"bcrypt.dll\0").as_ptr(), 0x800);
    load(handle, b"api-ms-win-core-path-l1-1-0.dll", wide(b"api-ms-win-core-path-l1-1-0.dll\0").as_ptr(), 0x800);
    private_load(handle, b"vcruntime140.dll", b"vcruntime140.dll\0");
    load(handle, b"api-ms-win-crt-stdio-l1-1-0.dll", wide(b"api-ms-win-crt-stdio-l1-1-0.dll\0").as_ptr(), 0x800);
    load(handle, b"api-ms-win-crt-environment-l1-1-0.dll", wide(b"api-ms-win-crt-environment-l1-1-0.dll\0").as_ptr(), 0x800);
    load(handle, b"api-ms-win-crt-string-l1-1-0.dll", wide(b"api-ms-win-crt-string-l1-1-0.dll\0").as_ptr(), 0x800);
    load(handle, b"api-ms-win-crt-heap-l1-1-0.dll", wide(b"api-ms-win-crt-heap-l1-1-0.dll\0").as_ptr(), 0x800);
    load(handle, b"api-ms-win-crt-runtime-l1-1-0.dll", wide(b"api-ms-win-crt-runtime-l1-1-0.dll\0").as_ptr(), 0x800);
    load(handle, b"api-ms-win-crt-locale-l1-1-0.dll", wide(b"api-ms-win-crt-locale-l1-1-0.dll\0").as_ptr(), 0x800);
    load(handle, b"api-ms-win-crt-convert-l1-1-0.dll", wide(b"api-ms-win-crt-convert-l1-1-0.dll\0").as_ptr(), 0x800);
    load(handle, b"api-ms-win-crt-math-l1-1-0.dll", wide(b"api-ms-win-crt-math-l1-1-0.dll\0").as_ptr(), 0x800);
    load(handle, b"api-ms-win-crt-time-l1-1-0.dll", wide(b"api-ms-win-crt-time-l1-1-0.dll\0").as_ptr(), 0x800);
    load(handle, b"api-ms-win-crt-process-l1-1-0.dll", wide(b"api-ms-win-crt-process-l1-1-0.dll\0").as_ptr(), 0x800);
    load(handle, b"api-ms-win-crt-conio-l1-1-0.dll", wide(b"api-ms-win-crt-conio-l1-1-0.dll\0").as_ptr(), 0x800);
    load(handle, b"api-ms-win-crt-filesystem-l1-1-0.dll", wide(b"api-ms-win-crt-filesystem-l1-1-0.dll\0").as_ptr(), 0x800);
    private_load(handle, b"python313.dll", b"python313.dll\0");
    write(handle, b"DONE\n");
    ExitProcess(0);
}

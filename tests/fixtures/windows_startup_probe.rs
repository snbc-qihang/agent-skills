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
    let digits = b"0123456789ABCDEF";
    let mut status = *b"0x00000000\n";
    let mut index = 0;
    while index < 8 {
        status[index + 2] = digits[((error >> (28 - index * 4)) & 15) as usize];
        index += 1;
    }
    write(handle, b"RESULT ");
    write(handle, label);
    write(handle, b" ");
    write(handle, &status);
    if !module.is_null() && FreeLibrary(module) == 0 {
        ExitProcess(73);
    }
}

unsafe fn private_load(handle: *mut c_void, label: &[u8], suffix: &[u8]) {
    // GetModuleFileNameW identifies this owned executable, never argv/CWD/PATH.
    // No initialization of the large stack buffer or implicit CRT memset.
    let mut storage = MaybeUninit::<[u16; 1024]>::uninit();
    let name = storage.as_mut_ptr().cast::<u16>();
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
    // DLL_LOAD_DIR|SYSTEM32 requires an absolute path and runs real DllMain.
    // https://learn.microsoft.com/windows/win32/api/libloaderapi/nf-libloaderapi-loadlibraryexw
    load(handle, label, name, 0x900);
}

#[no_mangle]
pub unsafe extern "system" fn probe_entry() -> ! {
    let handle = GetStdHandle(-11_i32 as u32);
    if handle.is_null() || handle as isize == -1 {
        ExitProcess(70);
    }
    write(handle, b"EA_NATIVE_DLL_PROBE_V1\n");
    // Fixed sequential observations; loaded-module state is not independent.
    load(handle, b"ucrtbase.dll", wide(b"ucrtbase.dll\0").as_ptr(), 0x800);
    load(handle, b"advapi32.dll", wide(b"advapi32.dll\0").as_ptr(), 0x800);
    load(handle, b"shell32.dll", wide(b"shell32.dll\0").as_ptr(), 0x800);
    load(handle, b"ole32.dll", wide(b"ole32.dll\0").as_ptr(), 0x800);
    load(handle, b"oleaut32.dll", wide(b"oleaut32.dll\0").as_ptr(), 0x800);
    private_load(handle, b"vcruntime140.dll", b"vcruntime140.dll\0");
    private_load(handle, b"python313.dll", b"python313.dll\0");
    write(handle, b"DONE\n");
    ExitProcess(0);
}

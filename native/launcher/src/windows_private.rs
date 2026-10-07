use super::Result;
use std::{ffi::c_void, mem, os::windows::ffi::OsStrExt, path::Path, ptr, slice};

type Handle = *mut c_void;

#[repr(C)]
struct AttributeTag {
    attributes: u32,
    tag: u32,
}

#[repr(C)]
struct AclSize {
    count: u32,
    used: u32,
    free: u32,
}

#[link(name = "kernel32")]
extern "system" {
    fn GetCurrentProcess() -> Handle;
    fn CloseHandle(handle: Handle) -> i32;
    fn LocalFree(memory: Handle) -> Handle;
    fn CreateFileW(
        name: *const u16,
        access: u32,
        share: u32,
        security: Handle,
        disposition: u32,
        flags: u32,
        template: Handle,
    ) -> Handle;
    fn GetFileInformationByHandleEx(handle: Handle, class: i32, output: Handle, size: u32) -> i32;
}

#[link(name = "advapi32")]
extern "system" {
    fn OpenProcessToken(process: Handle, access: u32, token: *mut Handle) -> i32;
    fn GetTokenInformation(
        token: Handle,
        class: i32,
        output: Handle,
        size: u32,
        length: *mut u32,
    ) -> i32;
    fn GetSecurityInfo(
        handle: Handle,
        kind: i32,
        information: u32,
        owner: *mut Handle,
        group: *mut Handle,
        dacl: *mut Handle,
        sacl: *mut Handle,
        descriptor: *mut Handle,
    ) -> u32;
    fn IsValidAcl(acl: Handle) -> i32;
    fn GetAclInformation(acl: Handle, output: Handle, size: u32, class: i32) -> i32;
    fn GetAce(acl: Handle, index: u32, ace: *mut Handle) -> i32;
    fn IsValidSid(sid: Handle) -> i32;
    fn GetLengthSid(sid: Handle) -> u32;
    fn EqualSid(left: Handle, right: Handle) -> i32;
}

struct OwnedHandle(Handle);
impl Drop for OwnedHandle {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}

struct Security(Handle);
impl Drop for Security {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe {
                LocalFree(self.0);
            }
        }
    }
}

fn current_user() -> Result<Vec<u8>> {
    let mut token = ptr::null_mut();
    if unsafe { OpenProcessToken(GetCurrentProcess(), 0x8, &mut token) } == 0 {
        return Err("current Windows user cannot be inspected");
    }
    let token = OwnedHandle(token);
    let mut length = 0;
    unsafe {
        GetTokenInformation(token.0, 1, ptr::null_mut(), 0, &mut length);
    }
    if !(mem::size_of::<Handle>() as u32..=65536).contains(&length) {
        return Err("current Windows user token is invalid");
    }
    let mut bytes = vec![0u8; length as usize];
    if unsafe { GetTokenInformation(token.0, 1, bytes.as_mut_ptr().cast(), length, &mut length) }
        == 0
    {
        return Err("current Windows user cannot be read");
    }
    let sid = unsafe { ptr::read_unaligned(bytes.as_ptr().cast::<Handle>()) };
    let offset = (sid as usize)
        .checked_sub(bytes.as_ptr() as usize)
        .filter(|offset| *offset <= bytes.len().saturating_sub(8))
        .ok_or("current Windows user identity is invalid")?;
    let size = 8 + 4 * usize::from(bytes[offset + 1]);
    if size > bytes.len() - offset || unsafe { IsValidSid(sid) } == 0 {
        return Err("current Windows user identity is invalid");
    }
    Ok(bytes[offset..offset + size].to_vec())
}

/// Recheck every control path at invocation, even after setup succeeded.
/// Administrators are not an implicit trustee of single-user Runtime data.
pub(super) fn check(path: &Path) -> Result<()> {
    let user = current_user()?;
    let user_sid = user.as_ptr() as Handle;
    let name: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    let file = unsafe {
        CreateFileW(
            name.as_ptr(),
            0x20080,
            7,
            ptr::null_mut(),
            3,
            0x02200000,
            ptr::null_mut(),
        )
    };
    if file.is_null() || file as isize == -1 {
        return Err("private runtime path cannot be opened");
    }
    let file = OwnedHandle(file);
    let mut attributes = AttributeTag {
        attributes: 0,
        tag: 0,
    };
    if unsafe {
        GetFileInformationByHandleEx(
            file.0,
            9,
            (&mut attributes as *mut AttributeTag).cast(),
            mem::size_of::<AttributeTag>() as u32,
        )
    } == 0
        || attributes.attributes & 0x400 != 0
    {
        return Err("private runtime path is unsafe");
    }
    let mut owner = ptr::null_mut();
    let mut dacl = ptr::null_mut();
    let mut security = Security(ptr::null_mut());
    let status = unsafe {
        GetSecurityInfo(
            file.0,
            1,
            5,
            &mut owner,
            ptr::null_mut(),
            &mut dacl,
            ptr::null_mut(),
            &mut security.0,
        )
    };
    if status != 0
        || owner.is_null()
        || dacl.is_null()
        || unsafe { IsValidSid(owner) } == 0
        || unsafe { EqualSid(owner, user_sid) } == 0
    {
        return Err("runtime path is not private to the current Windows user");
    }
    let mut info = AclSize {
        count: 0,
        used: 0,
        free: 0,
    };
    if unsafe { IsValidAcl(dacl) } == 0
        || unsafe {
            GetAclInformation(
                dacl,
                (&mut info as *mut AclSize).cast(),
                mem::size_of::<AclSize>() as u32,
                2,
            )
        } == 0
        || !(1..=1024).contains(&info.count)
        || !(8..=65535).contains(&info.used)
    {
        return Err("private runtime DACL is missing or invalid");
    }
    let system = [1u8, 1, 0, 0, 0, 0, 0, 5, 18, 0, 0, 0];
    let mut user_allowed = false;
    for index in 0..info.count {
        let mut ace = ptr::null_mut();
        if unsafe { GetAce(dacl, index, &mut ace) } == 0 || ace.is_null() {
            return Err("private runtime DACL cannot be inspected");
        }
        let offset = (ace as usize)
            .checked_sub(dacl as usize)
            .filter(|offset| *offset >= 8 && *offset <= info.used as usize - 8)
            .ok_or("private runtime ACE is invalid")?;
        let header = unsafe { slice::from_raw_parts(ace.cast::<u8>(), 8) };
        let size = usize::from(u16::from_le_bytes([header[2], header[3]]));
        if header[0] > 1 || size < 16 || size > info.used as usize - offset {
            return Err("private runtime ACE is unsupported");
        }
        let sid = unsafe { ace.cast::<u8>().add(8) };
        let sid_header = unsafe { slice::from_raw_parts(sid, 8) };
        if 8 + 4 * usize::from(sid_header[1]) > size - 8
            || unsafe { IsValidSid(sid as Handle) } == 0
            || unsafe { GetLengthSid(sid as Handle) } as usize > size - 8
        {
            return Err("private runtime ACE identity is invalid");
        }
        let mask = u32::from_le_bytes([header[4], header[5], header[6], header[7]]);
        if header[0] == 0 && mask != 0 {
            let is_user = unsafe { EqualSid(sid as Handle, user_sid) } != 0;
            if !is_user && unsafe { EqualSid(sid as Handle, system.as_ptr() as Handle) } == 0 {
                return Err("runtime path is not private to the current Windows user and SYSTEM");
            }
            user_allowed |= is_user && header[1] & 0x8 == 0;
        }
    }
    if !user_allowed {
        return Err("private runtime path does not grant current user access");
    }
    Ok(())
}

"""Safely remove / eject storage devices (Windows, no administrator rights needed).

Removable drives (USB sticks, SD cards, USB disks) are ejected the same way the
"Safely Remove Hardware" tray icon does it: find the disk behind the drive
letter, walk up the Plug and Play tree to the removable device and ask the
PnP manager to eject it (``CM_Request_Device_EjectW``). Windows refuses - with
a reason - while a program still has files open. Optical drives get their tray
opened instead (``IOCTL_STORAGE_EJECT_MEDIA``).
"""
from __future__ import annotations

import ctypes
import sys
import time
import uuid
from ctypes import wintypes

from .storage_info import DISC, DRIVE_FIXED, DRIVE_REMOVABLE, SDCARD, USB, DeviceInfo

IS_WINDOWS = sys.platform == "win32"

IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x2D1080
IOCTL_STORAGE_EJECT_MEDIA = 0x2D4808
FILE_SHARE_READ_WRITE = 0x1 | 0x2
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
DIGCF_PRESENT, DIGCF_DEVICEINTERFACE = 0x2, 0x10
CR_SUCCESS = 0
DN_REMOVABLE = 0x4000

GUID_DEVINTERFACE_DISK = "53f56307-b6bf-11d0-94f2-00a0c91efb8b"
GUID_DEVINTERFACE_CDROM = "53f56308-b6bf-11d0-94f2-00a0c91efb8b"

VETO_REASONS = {
    1: "a legacy device driver is blocking it",
    2: "a program has it open",
    3: "Windows has it open",
    4: "a driver is blocking it",
    5: "a program still has files open on it",
    6: "a program is still using it",
    7: "its driver does not allow removal",
    8: "it does not support removal",
    9: "a driver is busy with it",
    10: "a driver is blocking it",
    11: "it is not a removable device",
    12: "its driver cannot be stopped",
}


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> "GUID":
        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)


class STORAGE_DEVICE_NUMBER(ctypes.Structure):
    _fields_ = [("DeviceType", wintypes.DWORD), ("DeviceNumber", wintypes.DWORD),
                ("PartitionNumber", wintypes.DWORD)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID), ("Flags", wintypes.DWORD),
                ("Reserved", ctypes.c_size_t)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("ClassGuid", GUID), ("DevInst", wintypes.DWORD),
                ("Reserved", ctypes.c_size_t)]


def can_eject(dev: DeviceInfo) -> bool:
    """True for devices Windows lets you safely remove or eject."""
    if not IS_WINDOWS or len(dev.letter) != 2:
        return False
    if dev.kind in (USB, SDCARD, DISC) or dev.drive_type == DRIVE_REMOVABLE:
        return True
    # external USB/SD disks show up as fixed drives
    return dev.drive_type == DRIVE_FIXED and dev.bus.lower() in ("usb", "sd")


def _api():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    sapi = ctypes.WinDLL("setupapi", use_last_error=True)
    sapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    sapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    sapi.SetupDiEnumDeviceInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID),
                                                 wintypes.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
    sapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                                      ctypes.c_void_p, wintypes.DWORD,
                                                      ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(SP_DEVINFO_DATA)]
    sapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
    cfg = ctypes.WinDLL("cfgmgr32")
    cfg.CM_Get_Parent.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.ULONG]
    cfg.CM_Get_DevNode_Status.argtypes = [ctypes.POINTER(wintypes.ULONG), ctypes.POINTER(wintypes.ULONG),
                                          wintypes.DWORD, wintypes.ULONG]
    cfg.CM_Request_Device_EjectW.argtypes = [wintypes.DWORD, ctypes.POINTER(ctypes.c_int), wintypes.LPWSTR,
                                             wintypes.ULONG, wintypes.ULONG]
    return k32, sapi, cfg


def _open(k32, path: str):
    # zero access rights: enough for the IOCTLs used here, and no admin needed
    h = k32.CreateFileW(path, 0, FILE_SHARE_READ_WRITE, None, OPEN_EXISTING, 0, None)
    return None if h in (None, INVALID_HANDLE_VALUE) else h


def _device_number(k32, path: str) -> tuple[int, int] | None:
    h = _open(k32, path)
    if h is None:
        return None
    try:
        sdn = STORAGE_DEVICE_NUMBER()
        got = wintypes.DWORD()
        if not k32.DeviceIoControl(h, IOCTL_STORAGE_GET_DEVICE_NUMBER, None, 0, ctypes.byref(sdn),
                                   ctypes.sizeof(sdn), ctypes.byref(got), None):
            return None
        return sdn.DeviceType, sdn.DeviceNumber
    finally:
        k32.CloseHandle(h)


def _devinst_for(k32, sapi, interface_guid: str, number: tuple[int, int]) -> int | None:
    """PnP device instance of the disk/cdrom interface with the given device number."""
    guid = GUID.parse(interface_guid)
    hdev = sapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if hdev in (None, INVALID_HANDLE_VALUE):
        return None
    try:
        i = 0
        while True:
            ifd = SP_DEVICE_INTERFACE_DATA(cbSize=ctypes.sizeof(SP_DEVICE_INTERFACE_DATA))
            if not sapi.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(guid), i, ctypes.byref(ifd)):
                return None
            i += 1
            need = wintypes.DWORD()
            sapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(ifd), None, 0, ctypes.byref(need), None)
            if not need.value:
                continue
            buf = ctypes.create_string_buffer(need.value)
            # SP_DEVICE_INTERFACE_DETAIL_DATA_W.cbSize: 8 on 64-bit, 6 on 32-bit
            ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            did = SP_DEVINFO_DATA(cbSize=ctypes.sizeof(SP_DEVINFO_DATA))
            if not sapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(ifd), buf, need, None, ctypes.byref(did)):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
            if _device_number(k32, path) == number:
                return did.DevInst
    finally:
        sapi.SetupDiDestroyDeviceInfoList(hdev)


def _removable_ancestor(cfg, devinst: int) -> int:
    """The nearest device in the PnP tree flagged removable (e.g. the USB mass storage device)."""
    cur = devinst
    for _ in range(16):
        status, problem = wintypes.ULONG(), wintypes.ULONG()
        if cfg.CM_Get_DevNode_Status(ctypes.byref(status), ctypes.byref(problem), cur, 0) == CR_SUCCESS \
                and status.value & DN_REMOVABLE:
            return cur
        parent = wintypes.DWORD()
        if cfg.CM_Get_Parent(ctypes.byref(parent), cur, 0) != CR_SUCCESS:
            break
        cur = parent.value
    return devinst


def _eject_tray(k32, letter: str) -> tuple[bool, str]:
    h = _open(k32, f"\\\\.\\{letter}")
    if h is None:
        return False, f"Could not open {letter} ({ctypes.FormatError(ctypes.get_last_error())})"
    try:
        got = wintypes.DWORD()
        if k32.DeviceIoControl(h, IOCTL_STORAGE_EJECT_MEDIA, None, 0, None, 0, ctypes.byref(got), None):
            return True, f"Ejected the disc in {letter}"
        return False, f"Could not eject {letter} ({ctypes.FormatError(ctypes.get_last_error())})"
    finally:
        k32.CloseHandle(h)


def _removal_target(k32, sapi, cfg, letter: str) -> int | None:
    """PnP device instance that Windows ejects to remove the drive with this letter."""
    number = _device_number(k32, f"\\\\.\\{letter}")
    if number is None:
        return None
    devinst = _devinst_for(k32, sapi, GUID_DEVINTERFACE_DISK, number)
    return None if devinst is None else _removable_ancestor(cfg, devinst)


def drives_removed_together(dev: DeviceInfo, devices: list[DeviceInfo]) -> list[DeviceInfo]:
    """Every drive that disappears when ``dev`` is removed (e.g. all slots of a card reader)."""
    if not can_eject(dev) or dev.kind == DISC:
        return [dev]
    k32, sapi, cfg = _api()
    target = _removal_target(k32, sapi, cfg, dev.letter.upper())
    if target is None:
        return [dev]
    return [d for d in devices if d is dev or (can_eject(d) and d.kind != DISC and d.letter
                                               and _removal_target(k32, sapi, cfg, d.letter.upper()) == target)]


def safely_remove(dev: DeviceInfo, attempts: int = 3) -> tuple[bool, str]:
    """Blocking (run it off the UI thread). Returns (success, human-readable message)."""
    if not can_eject(dev):
        return False, f"{dev.title} cannot be safely removed"
    letter = dev.letter.upper()
    k32, sapi, cfg = _api()
    if dev.kind == DISC:
        return _eject_tray(k32, letter)
    target = _removal_target(k32, sapi, cfg, letter)
    if target is None:
        return False, f"Could not find the device behind {letter}"
    reason = "Windows refused"
    for attempt in range(attempts):
        veto = ctypes.c_int(0)
        name = ctypes.create_unicode_buffer(260)
        cr = cfg.CM_Request_Device_EjectW(target, ctypes.byref(veto), name, 260, 0)
        if cr == CR_SUCCESS and veto.value == 0:
            return True, f"{dev.title} can now be safely removed"
        if veto.value:
            reason = VETO_REASONS.get(veto.value, "Windows refused")
        else:
            reason = f"Windows refused (error {cr})"
        time.sleep(0.5 * (attempt + 1))     # handles from a just-finished scan may still be closing
    return False, f"{dev.title} cannot be removed right now: {reason}. Close any programs using it and try again."

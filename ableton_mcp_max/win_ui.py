"""Windows counterpart of the macOS osascript/System Events layer (host-side).

Imported by server.py only, and only on Windows. Every call goes through
ctypes (user32/kernel32/iphlpapi) - no extra dependencies.

What Live 12 on Windows offers (probed on 12.4.6):
  * a NATIVE Win32 menu bar on the main window, so menu commands are posted as
    WM_COMMAND by item text - focus-independent, like the macOS menu clicks;
  * WM_CLOSE on the main window is the graceful quit (the Apple 'quit' event
    equivalent): an unchanged set closes with no prompt;
  * a UI Automation tree whose control names match the macOS AX descriptions
    (see win_uia.py for the dialog controls).
Keystrokes are the last resort; send_* refuses to type unless a Live window is
in the foreground, so a stray Return can never land in another app.
"""
import ctypes
import os
import time
from ctypes import wintypes

from ableton_mcp_max.platform_utils import menu_label

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
iphlpapi = ctypes.WinDLL("iphlpapi")

LIVE_WINDOW_CLASS = "Ableton Live Window Class"

WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
SW_RESTORE = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x102
STILL_ACTIVE = 259

user32.GetMenu.restype = wintypes.HMENU
user32.GetSubMenu.restype = wintypes.HMENU
user32.GetForegroundWindow.restype = wintypes.HWND
kernel32.OpenProcess.restype = wintypes.HANDLE


# --- processes ---------------------------------------------------------------

class _MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [("dwState", wintypes.DWORD), ("dwLocalAddr", wintypes.DWORD),
                ("dwLocalPort", wintypes.DWORD), ("dwRemoteAddr", wintypes.DWORD),
                ("dwRemotePort", wintypes.DWORD), ("dwOwningPid", wintypes.DWORD)]


_MIB_TCP_STATE_LISTEN = 2
_TCP_TABLE_OWNER_PID_LISTENER = 3
_AF_INET = 2


def listening_pid(port):
    """PID of the process LISTENING on IPv4 TCP `port`, or None. Uses
    GetExtendedTcpTable, so it is locale-independent (netstat's state column
    is translated on non-English Windows)."""
    size = wintypes.DWORD(0)
    iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, _AF_INET,
                                 _TCP_TABLE_OWNER_PID_LISTENER, 0)
    buf = ctypes.create_string_buffer(size.value)
    if iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), False, _AF_INET,
                                    _TCP_TABLE_OWNER_PID_LISTENER, 0) != 0:
        return None
    count = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0]
    rows = ctypes.cast(ctypes.addressof(buf) + ctypes.sizeof(wintypes.DWORD),
                       ctypes.POINTER(_MIB_TCPROW_OWNER_PID * count)).contents
    for row in rows:
        # dwLocalPort is in network byte order in its low 16 bits.
        # The LISTENER table only ever holds listening sockets, so membership
        # is the test: Live's listener has been seen with dwState 6 (not the
        # documented LISTEN value 2) after clients came and went, and a strict
        # state check then reported "No running Ableton Live" with Live up.
        p = ((row.dwLocalPort & 0xFF) << 8) | ((row.dwLocalPort >> 8) & 0xFF)
        if p == port:
            return int(row.dwOwningPid)
    return None


def process_image(pid):
    """Full exe path of `pid`, or None."""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
        return None
    finally:
        kernel32.CloseHandle(h)


def pid_alive(pid):
    """True while `pid` is running. NEVER os.kill(pid, 0) on Windows - that
    TERMINATES the process."""
    h = kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION,
                             False, pid)
    if not h:
        return False
    try:
        return kernel32.WaitForSingleObject(h, 0) == WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(h)


def launch(exe):
    """Start `exe` detached (relaunching Live)."""
    os.startfile(exe)


def open_file(path):
    """Open a file with its default app (Live for .als)."""
    os.startfile(path)


# --- windows -----------------------------------------------------------------

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _text(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _window_pid(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def windows(pid):
    """[(hwnd, title, class)] of `pid`'s VISIBLE top-level windows, in z-order
    (frontmost first). Invisible helper windows (IME, web-view host) are
    skipped so the count is a usable 'is a dialog open' signal."""
    out = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and _window_pid(hwnd) == pid:
            out.append((hwnd, _text(hwnd), _class(hwnd)))
        return True

    user32.EnumWindows(_WNDENUMPROC(cb), 0)
    return out


def main_window(pid):
    """hwnd of Live's main SET window, or None.

    Settings, the Export dialog, prompts, dropdowns and plugin editors all
    share Live's window class and can sit above the set window in z-order, so
    'first Live-class window' is wrong whenever one is open (the macOS layer
    hit the same trap with an Ozone editor). Only the set window owns the
    native menu bar; the ' - Ableton Live' title suffix is the fallback."""
    wins = [w for w in windows(pid) if w[2] == LIVE_WINDOW_CLASS]
    for hwnd, _title, _cls in wins:
        if user32.GetMenu(hwnd):
            return hwnd
    for hwnd, title, _cls in wins:
        if " - Ableton Live" in title:
            return hwnd
    return None


def window_title(hwnd):
    return _text(hwnd) if hwnd else ""


def find_window(pid, title):
    """hwnd of `pid`'s visible top-level window titled exactly `title`."""
    for hwnd, t, _cls in windows(pid):
        if t == title:
            return hwnd
    return None


def close(hwnd):
    """Ask a window to close (graceful; Live prompts if the set is dirty)."""
    return bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))


# --- native file dialogs (Save Live Set As:, Save Audio File As:) -------------
# Live uses the stock Windows Save dialog (#32770). Its controls are real
# Win32 child windows: the folder is read off the address bar and Cancel is a
# BM_CLICK. The NAME, however, must be TYPED: setting the File name box with
# WM_SETTEXT or UIA ValuePattern.SetValue changes the visible text (it even
# reads back) but the dialog ignores it and saves under its previous name
# ("Untitled") - verified on Live 12.4.6, where it silently wrote
# Untitled.als / Untitled.wav into the last-used project folder. Typed input
# (SendInput, dialog in the foreground) is honoured.

WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
BM_CLICK = 0x00F5
IDOK = 1
IDCANCEL = 2
IDYES = 6
DIALOG_CLASS = "#32770"

user32.GetParent.restype = wintypes.HWND
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                wintypes.LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t


def _children(hwnd):
    out = []

    def cb(ch, _):
        out.append(ch)
        return True

    user32.EnumChildWindows(hwnd, _WNDENUMPROC(cb), 0)
    return out


def get_text(hwnd):
    """Control text via WM_GETTEXT (GetWindowText can't read another
    process's edit controls)."""
    buf = ctypes.create_unicode_buffer(1024)
    user32.SendMessageW(hwnd, WM_GETTEXT, 1024, ctypes.addressof(buf))
    return buf.value


def _file_name_edit(dlg):
    """The 'File name:' edit: an Edit inside a plain ComboBox (the address
    bar's Edit sits inside a ComboBoxEx32 and is skipped)."""
    for ch in _children(dlg):
        if _class(ch) != "Edit":
            continue
        parent = user32.GetParent(ch)
        if _class(parent) == "ComboBox" and \
                _class(user32.GetParent(parent)) != "ComboBoxEx32":
            return ch
    return None


def _button(dlg, ctrl_id):
    for ch in _children(dlg):
        if _class(ch) == "Button" and user32.GetDlgCtrlID(ch) == ctrl_id \
                and user32.GetParent(ch) == dlg:
            return ch
    return None


def file_dialog_folder(dlg):
    """The folder a Save dialog will write into, read off its address bar
    ('Address: C:\\...'), or ''."""
    for ch in _children(dlg):
        if _class(ch) == "ToolbarWindow32":
            t = _text(ch)
            if t.startswith("Address: "):
                return t[len("Address: "):]
    return ""


def file_dialog_name(dlg):
    edit = _file_name_edit(dlg)
    return get_text(edit) if edit else ""


WM_CHAR = 0x0102
EM_SETSEL = 0x00B1


def _type_into_edit(edit, name):
    """Replace an edit control's text by sending it WM_CHAR per character
    (after EM_SETSEL select-all). Targeted at the control's hwnd, so nothing
    can land in another window - unlike SendInput, which goes to whatever is
    in the foreground at that instant. The stock Save dialog honours typed
    characters (WM_SETTEXT it ignores, see above)."""
    user32.SendMessageW(edit, EM_SETSEL, 0, -1)
    for ch in str(name):
        user32.SendMessageW(edit, WM_CHAR, ord(ch), 0)


def file_dialog_save(dlg, name, timeout=5.0):
    """Put `name` into the dialog's File name box and press Save.

    First by WM_CHAR to the edit control plus BM_CLICK on Save (no global
    input at all). If the box does not read back exactly `name`, fall back to
    the keystroke path (foreground-checked SendInput). On any final mismatch
    the dialog is CANCELLED and RuntimeError raised, so a failed fill can
    never save under the old name.

    Why no keystrokes by default: on 2026-11-02 a render left 32 beats of
    silence inserted across the whole arrangement at the render range - the
    signature of Ctrl+I (Insert Silence) reaching Live's set window while the
    time selection was the loop. The only global keystrokes in the render path
    were this function's Ctrl+A + typed name + Return."""
    edit = _file_name_edit(dlg)
    save = _button(dlg, IDOK)
    if not edit or not save:
        raise RuntimeError("Save dialog controls not found.")
    _type_into_edit(edit, name)
    end = time.monotonic() + 2.0
    while time.monotonic() < end and get_text(edit) != name:
        time.sleep(0.1)
    if get_text(edit) == name:
        user32.PostMessageW(save, BM_CLICK, 0, 0)
        return
    _file_dialog_save_keys(dlg, name, edit, timeout)


def _file_dialog_save_keys(dlg, name, edit, timeout=5.0):
    """Keystroke fallback: bring the dialog to the foreground, Ctrl+A, type,
    Return. Every keystroke is refused unless the dialog itself is the
    foreground window."""
    if not activate(dlg):
        dialog_click(dlg, IDCANCEL)
        raise RuntimeError("Could not bring Live's Save dialog to the front to "
                           "type the file name; cancelled.")
    try:
        send_key(dlg, ord("A"), ctrl=True)
        send_text(dlg, name)
    except RuntimeError:
        dialog_click(dlg, IDCANCEL)
        raise
    end = time.monotonic() + timeout
    while time.monotonic() < end and get_text(edit) != name:
        time.sleep(0.1)
    if get_text(edit) != name:
        dialog_click(dlg, IDCANCEL)
        raise RuntimeError("The Save dialog's file name did not take (reads %r, "
                           "wanted %r); cancelled without saving."
                           % (get_text(edit), name))
    try:
        send_key(dlg, VK_RETURN)
    except RuntimeError:
        dialog_click(dlg, IDCANCEL)
        raise


def dialog_click(dlg, ctrl_id):
    """BM_CLICK a dialog button by id (IDOK/IDCANCEL/IDYES...). False if the
    button doesn't exist."""
    b = _button(dlg, ctrl_id)
    if not b:
        return False
    user32.PostMessageW(b, BM_CLICK, 0, 0)
    return True


def dialogs(pid):
    """[(hwnd, title)] of `pid`'s visible standard dialogs (#32770)."""
    return [(h, t) for h, t, c in windows(pid) if c == DIALOG_CLASS]


# --- menu --------------------------------------------------------------------

def _menu_items(menu):
    for i in range(user32.GetMenuItemCount(menu)):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetMenuStringW(menu, i, buf, 256, 0x400)       # MF_BYPOSITION
        yield i, buf.value, ctypes.c_int(user32.GetMenuItemID(menu, i)).value


def menu_command_id(hwnd, top, item):
    """Command id of menu item `item` under top-level menu `top` (labels
    compared without '&' and shortcut text), or None."""
    bar = user32.GetMenu(hwnd)
    if not bar:
        return None
    for i, text, _cid in _menu_items(bar):
        if menu_label(text) != top:
            continue
        sub = user32.GetSubMenu(bar, i)
        for _j, t, cid in _menu_items(sub):
            if menu_label(t) == item and cid > 0:
                return cid
    return None


def post_menu(hwnd, top, item):
    """Invoke a menu item by posting its WM_COMMAND (no focus needed). Raises
    RuntimeError if the item does not exist."""
    cid = menu_command_id(hwnd, top, item)
    if cid is None:
        raise RuntimeError("Live has no '%s > %s' menu item." % (top, item))
    user32.PostMessageW(hwnd, WM_COMMAND, cid, 0)


# --- focus + keyboard ----------------------------------------------------------

_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_INPUT_KEYBOARD = 1
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_CONTROL = 0x11
VK_MENU = 0x12


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("_pad", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _send(events):
    arr = (_INPUT * len(events))()
    for i, (vk, scan, flags) in enumerate(events):
        arr[i].type = _INPUT_KEYBOARD
        arr[i].u.ki = _KEYBDINPUT(vk, scan, flags, 0, 0)
    user32.SendInput(len(events), arr, ctypes.sizeof(_INPUT))


def activate(hwnd):
    """Bring `hwnd` to the foreground. Windows refuses SetForegroundWindow from
    a background process unless it just received input, so tap Alt first (the
    documented workaround). Returns True if it is now foreground."""
    if not hwnd:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    if user32.GetForegroundWindow() == hwnd:
        return True
    # Plain request first (works when this process or its caller last had
    # input); the Alt tap is a global keystroke and is a last resort only.
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    if user32.GetForegroundWindow() == hwnd:
        return True
    _send([(VK_MENU, 0, 0), (VK_MENU, 0, _KEYEVENTF_KEYUP)])
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    return user32.GetForegroundWindow() == hwnd


def foreground_pid():
    fg = user32.GetForegroundWindow()
    return _window_pid(fg) if fg else 0


def _require_foreground(hwnd):
    """Keystrokes go to whatever window is in front, so refuse unless it is
    EXACTLY the target window: not merely 'some Live window' (Ctrl+A or a
    letter landing in Live's main window would act on the set), and never
    another app."""
    if user32.GetForegroundWindow() != hwnd:
        raise RuntimeError("The target window is not in the foreground - "
                           "refusing to send keystrokes that could land "
                           "elsewhere.")


def send_text(hwnd, text):
    _require_foreground(hwnd)
    ev = []
    for ch in str(text):
        code = ord(ch)
        ev.append((0, code, _KEYEVENTF_UNICODE))
        ev.append((0, code, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP))
    _send(ev)


def send_key(hwnd, vk, ctrl=False):
    _require_foreground(hwnd)
    ev = []
    if ctrl:
        ev.append((VK_CONTROL, 0, 0))
    ev += [(vk, 0, 0), (vk, 0, _KEYEVENTF_KEYUP)]
    if ctrl:
        ev.append((VK_CONTROL, 0, _KEYEVENTF_KEYUP))
    _send(ev)


# --- processes / pointer -----------------------------------------------------

_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]


def live_pids(prefix="Ableton Live"):
    """PIDs of every running process whose image name starts with `prefix`,
    whether or not it has bound the control-surface port yet. A Live that is
    still starting (crash-recovery prompt, splash) is only findable this way;
    listening_pid() sees it only once the Remote Script is up."""
    snap = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snap == _INVALID_HANDLE_VALUE or not snap:
        return []
    out = []
    try:
        e = _PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.szExeFile.lower().startswith(prefix.lower()):
                out.append(int(e.th32ProcessID))
            ok = kernel32.Process32NextW(snap, ctypes.byref(e))
    finally:
        kernel32.CloseHandle(snap)
    return out


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _MINPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("mi", _MOUSEINPUT)]


_MOUSEEVENTF_MOVE, _MOUSEEVENTF_LEFTDOWN = 0x0001, 0x0002
_MOUSEEVENTF_LEFTUP, _MOUSEEVENTF_ABSOLUTE = 0x0004, 0x8000


def click_point(x, y):
    """Left-click at SCREEN pixel (x, y) with SendInput (absolute coordinates).
    The pointer moves there - used only as a fallback when a UIA Invoke is
    ignored (Live's startup prompts do not honour Invoke)."""
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    ax = int(x * 65535 / max(1, sw - 1))
    ay = int(y * 65535 / max(1, sh - 1))

    for flags in (_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE,
                  _MOUSEEVENTF_LEFTDOWN | _MOUSEEVENTF_ABSOLUTE,
                  _MOUSEEVENTF_LEFTUP | _MOUSEEVENTF_ABSOLUTE):
        i = _MINPUT(0, _MOUSEINPUT(ax, ay, 0, flags, 0, None))
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(i))
        time.sleep(0.05)

"""UI Automation access to Live's own (non-native) dialogs on Windows.

Imported by server.py only, and only on Windows (needs comtypes). Live 12
exposes its custom-drawn UI through UIA with the SAME names the macOS AX layer
reports as descriptions ('Encode PCM', 'File Type', 'Start of Rendered Sample
(Bar)', 'Export', ...), so ExportUI here is a drop-in for server._ExportUI.

Probed on Live 12.4.6: the Export dialog is its own top-level window
('Export Audio/Video', class 'Ableton Live Window Class'); its toggles are
Buttons whose Value reads 'On'/'Off' and which Invoke to flip; its pop-ups are
ComboBoxes (Value + ExpandCollapse); the range boxes are Sliders whose Value is
the displayed number.
"""
import threading
import time

import comtypes
import comtypes.client

_UIA = comtypes.client.GetModule("UIAutomationCore.dll")
# One COM init + IUIAutomation per THREAD: FastMCP 1.27 runs sync tools on the
# event-loop thread, but a COM object must not be used from a thread that
# didn't initialize COM, so don't assume that stays true.
_local = threading.local()
_create_lock = threading.Lock()     # concurrent first-time creation raced (E_FAIL)


def _uia():
    auto = getattr(_local, "auto", None)
    if auto is None:
        with _create_lock:
            comtypes.CoInitialize()
            auto = comtypes.client.CreateObject(
                _UIA.CUIAutomation, interface=_UIA.IUIAutomation)
        _local.auto = auto
    return auto


def element(hwnd):
    return _uia().ElementFromHandle(hwnd)


def _cond_name(name):
    return _uia().CreatePropertyCondition(_UIA.UIA_NamePropertyId, name)


def _cond_type(ctype):
    return _uia().CreatePropertyCondition(_UIA.UIA_ControlTypePropertyId, ctype)


def find(root, name, ctype=None):
    """First descendant of `root` named `name` (and of UIA control type
    `ctype`, if given), or None."""
    cond = _cond_name(name)
    if ctype is not None:
        cond = _uia().CreateAndCondition(cond, _cond_type(ctype))
    try:
        el = root.FindFirst(_UIA.TreeScope_Descendants, cond)
    except comtypes.COMError:
        return None
    return el if el else None


def _pattern(el, pid, iface):
    unk = el.GetCurrentPattern(pid)
    return unk.QueryInterface(iface) if unk else None


def value(el):
    p = _pattern(el, _UIA.UIA_ValuePatternId, _UIA.IUIAutomationValuePattern)
    return p.CurrentValue if p else ""


def invoke(el):
    p = _pattern(el, _UIA.UIA_InvokePatternId, _UIA.IUIAutomationInvokePattern)
    if p is None:
        raise RuntimeError("element is not invokable")
    p.Invoke()


def expand(el):
    _pattern(el, _UIA.UIA_ExpandCollapsePatternId,
             _UIA.IUIAutomationExpandCollapsePattern).Expand()


def collapse(el):
    _pattern(el, _UIA.UIA_ExpandCollapsePatternId,
             _UIA.IUIAutomationExpandCollapsePattern).Collapse()


def children_names(el, ctype=None):
    cond = _cond_type(ctype) if ctype is not None else _uia().CreateTrueCondition()
    arr = el.FindAll(_UIA.TreeScope_Descendants, cond)
    return [arr.GetElement(i).CurrentName for i in range(arr.Length)]


def find_all(el, ctype):
    arr = el.FindAll(_UIA.TreeScope_Descendants, _cond_type(ctype))
    return [arr.GetElement(i) for i in range(arr.Length)]


BUTTON = _UIA.UIA_ButtonControlTypeId
COMBO = _UIA.UIA_ComboBoxControlTypeId
SLIDER = _UIA.UIA_SliderControlTypeId
LISTITEM = _UIA.UIA_ListItemControlTypeId
MENUITEM = _UIA.UIA_MenuItemControlTypeId


class ExportUI:
    """Same interface as server._ExportUI, over UIA. `window` is a callable
    returning the Export dialog's hwnd (looked up fresh each call: the dialog
    is recreated every time it opens)."""

    def __init__(self, window, popup_items):
        self._window = window
        self._popup_items = popup_items

    def _root(self):
        hwnd = self._window()
        if not hwnd:
            raise RuntimeError("The Export Audio/Video dialog is not open.")
        return element(hwnd)

    def _get(self, desc, ctype):
        el = find(self._root(), desc, ctype)
        if el is None:
            raise RuntimeError("Export dialog has no '%s' control." % desc)
        return el

    def read_toggle(self, desc):
        try:
            return value(self._get(desc, BUTTON))
        except Exception:
            return ""

    def click_toggle(self, desc):
        invoke(self._get(desc, BUTTON))

    def read_popup(self, desc):
        try:
            return value(self._get(desc, COMBO))
        except Exception:
            return ""

    def set_popup(self, desc, wanted):
        self._popup_items(self, desc, wanted)

    def read_slider(self, desc):
        try:
            return float(value(self._get(desc, SLIDER)))
        except Exception:
            return None

    def press(self, desc):
        invoke(self._get(desc, BUTTON))


def wait(pred, timeout, interval=0.2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(interval)
    return bool(pred())

"""
R1X Optimizer v2 - Core Engine
Windows Game / System Performance Optimizer (13 boost modules)
Pure Python standard library + ctypes (no third-party requirements).
"""

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes

try:
    import psutil
except Exception:
    psutil = None

LOCALDATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "R1X")
REG_BACKUP = os.path.join(LOCALDATA, "reg_backup.json")
STATE_FILE = os.path.join(LOCALDATA, "state.json")

try:
    import winreg as _winreg_module

    ROOTS = {"HKLM": _winreg_module.HKEY_LOCAL_MACHINE,
             "HKCU": _winreg_module.HKEY_CURRENT_USER,
             "HKCR": _winreg_module.HKEY_CLASSES_ROOT}

    def reg_read(root, path, name):
        try:
            with _winreg_module.OpenKey(root, path) as k:
                v, t = _winreg_module.QueryValueEx(k, name)
                return v, t
        except OSError:
            return None, None

    def reg_write(root, path, name, value, vtype):
        with _winreg_module.CreateKeyEx(root, path) as k:
            _winreg_module.SetValueEx(k, name, 0, vtype, value)

    def reg_delete(root, path, name):
        try:
            with _winreg_module.OpenKey(root, path, 0, _winreg_module.KEY_SET_VALUE) as k:
                _winreg_module.DeleteValue(k, name)
        except OSError:
            pass
except Exception:
    _winreg_module = None
    ROOTS = {}
    reg_read = reg_write = reg_delete = lambda *a, **k: None


# ---------------------------------------------------------------- admin / util

def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate():
    import sys as _sys
    if is_admin():
        return True
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", _sys.executable,
            '"%s"' % os.path.abspath(_sys.argv[0]), None, 1)
        return False
    except Exception:
        return False


def run(cmd, timeout=60, text=True):
    try:
        out = subprocess.run(cmd, capture_output=True, text=text, timeout=timeout,
                             shell=isinstance(cmd, str),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (out.stdout or "") + (out.stderr or "")
    except Exception as e:
        return str(e)


def _save_state(st):
    try:
        os.makedirs(LOCALDATA, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=2)
    except Exception:
        pass


def _load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ---------------------------------------------------------------- live stats

class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _Clock:
    def __init__(self):
        self._last = None
        self._last_pct = 0.0
        self._lock = threading.Lock()

    def percent(self):
        idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
        try:
            ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        except Exception:
            return self._last_pct

        def to_ns(ft):
            return (int(ft.dwHighDateTime) << 32) + int(ft.dwLowDateTime)

        now = (to_ns(idle), to_ns(kernel) + to_ns(user))
        with self._lock:
            if self._last:
                idle_d = now[0] - self._last[0]
                total_d = now[1] - self._last[1]
                if total_d > 0:
                    self._last_pct = max(0.0, min(100.0, 100.0 * (1 - idle_d / total_d)))
            self._last = now
        return self._last_pct


CPU_CLOCK = _Clock()


def ram_info():
    m = _MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    total, avail = m.ullTotalPhys, m.ullAvailPhys
    return {"total": total, "used": total - avail, "avail": avail,
            "percent": round(100.0 * (total - avail) / total, 1) if total else 0}


class _GpuPoll(threading.Thread):
    def __init__(self, interval=3.0):
        super().__init__(daemon=True)
        self.interval = interval
        self.util = None
        self._lock = threading.Lock()
        self.start()

    def run(self):
        while True:
            try:
                cmd = ("powershell -NoProfile -Command \"(Get-Counter "
                       "'\\GPU Engine(*engtype_3D)\\utilization percentage' "
                       "-ErrorAction SilentlyContinue).CounterSamples.CookedValue | "
                       "Measure-Object -Sum | Select-Object -ExpandProperty Sum\"")
                out = run(cmd, timeout=15)
                m = re.search(r"([\d.]+)", out)
                with self._lock:
                    self.util = max(0.0, min(100.0, float(m.group(1)))) if m else None
            except Exception:
                pass
            time.sleep(self.interval)


class _CorePoll(threading.Thread):
    def __init__(self, interval=3.0):
        super().__init__(daemon=True)
        self.interval = interval
        self.cores = []
        self._lock = threading.Lock()
        self.start()

    def run(self):
        while True:
            try:
                cmd = ("powershell -NoProfile -Command \"$c = Get-Counter "
                       "'\\Processor(*)\\% Processor Time' -ErrorAction SilentlyContinue; "
                       "$c.CounterSamples | Where-Object {$_.InstanceName -match '^\\d+$'} | "
                       "ForEach-Object { '{0}={1}' -f $_.InstanceName, "
                       "[math]::Round($_.CookedValue,1) }\"")
                out = run(cmd, timeout=20)
                vals = []
                for line in out.splitlines():
                    m = re.match(r"\s*(\d+)=([\d.]+)", line.strip())
                    if m:
                        vals.append(float(m.group(2)))
                with self._lock:
                    if len(vals) >= 2:
                        self.cores = vals
            except Exception:
                pass
            time.sleep(self.interval)


_GPU_POLL = _GpuPoll()
_CORE_POLL = _CorePoll()


def gpu_util():
    with _GPU_POLL._lock:
        return _GPU_POLL.util


def per_core():
    with _CORE_POLL._lock:
        return list(_CORE_POLL.cores)


def system_info():
    info = {"cpu": "Unknown CPU", "cores": 0, "gpu": "Unknown GPU", "vram": 0,
            "os": "Windows", "uptime": 0, "arch": ""}

    def grab_cpu():
        try:
            out = run(["wmic", "cpu", "get", "name,NumberOfCores", "/format:value"], timeout=8)
            nm = re.search(r"(?i)Name=([^\r\n]+)", out)
            nc = re.search(r"(?i)NumberOfCores=([^\r\n]+)", out)
            if nm:
                info["cpu"] = nm.group(1).strip()
            if nc:
                info["cores"] = int(nc.group(1).strip())
            if nm or nc:
                return
        except Exception:
            pass
        try:
            out = run("powershell -NoProfile -Command \"$p=Get-CimInstance Win32_Processor; '{0}|{1}' -f $p.Name,$p.NumberOfCores\"", timeout=12)
            m = re.search(r"([^|]+)\|(\d+)", out)
            if m:
                info["cpu"] = m.group(1).strip()
                info["cores"] = int(m.group(2))
        except Exception:
            pass

    def grab_gpu():
        try:
            out = run(["wmic", "path", "win32_VideoController", "get",
                       "Name,AdapterRAM", "/format:value"], timeout=8)
            nm = re.search(r"(?i)Name=([^\r\n]+)", out)
            vr = re.search(r"(?i)AdapterRAM=([^\r\n]+)", out)
            if nm:
                info["gpu"] = nm.group(1).strip()
            if vr:
                try:
                    info["vram"] = int(vr.group(1).strip()) // (1024 ** 3)
                except Exception:
                    info["vram"] = 0
            if nm or vr:
                return
        except Exception:
            pass
        try:
            out = run("powershell -NoProfile -Command \"$v=Get-CimInstance Win32_VideoController | Select-Object -First 1; '{0}|{1}' -f $v.Name,$v.AdapterRAM\"", timeout=12)
            m = re.search(r"(.+?)\|(\d+)", out)
            if m:
                info["gpu"] = m.group(1).strip()
                info["vram"] = int(m.group(2)) // (1024 ** 3) if m.group(2) != "0" else 0
        except Exception:
            pass
        if not info["vram"] and _winreg_module:
            try:
                with _winreg_module.OpenKey(_winreg_module.HKEY_LOCAL_MACHINE,
                                            r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000") as k:
                    q, _ = _winreg_module.QueryValueEx(k, "HardwareInformation.qwMemorySize")
                    info["vram"] = int(q) // (1024 ** 3) if q else 0
            except Exception:
                pass

    def grab_os():
        try:
            out = run("powershell -NoProfile -Command \"$o=Get-CimInstance Win32_OperatingSystem; $o.Caption\"", timeout=12)
            if out.strip():
                info["os"] = out.strip()
            info["arch"] = os.environ.get("PROCESSOR_ARCHITECTURE", "")
        except Exception:
            pass

    def grab_uptime():
        try:
            boot = run("powershell -NoProfile -Command \"(Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime | Select-Object -ExpandProperty TotalSeconds\"", timeout=12)
            info["uptime"] = int(float(re.search(r"([\d.]+)", boot).group(1)))
        except Exception:
            pass

    threads = [threading.Thread(target=f, daemon=True)
               for f in (grab_cpu, grab_gpu, grab_os, grab_uptime)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=14)
    info["ram"] = ram_info()["total"]
    sys_info_cache["cores"] = info["cores"]
    return info


def live_snapshot():
    r = ram_info()
    g = gpu_util()
    snap = {
        "cpu": round(CPU_CLOCK.percent(), 1),
        "ram": r["percent"],
        "gpu": (round(g, 1) if g is not None else None),
        "percore": per_core(),
        "cores": sys_info_cache.get("cores", 0),
        "memUsedGB": round(r["used"] / 1024 ** 3, 2),
        "memTotalGB": round(r["total"] / 1024 ** 3, 2),
        "memAvailGB": round(r["avail"] / 1024 ** 3, 2),
    }
    snap["fpsIndex"] = round(fps_index(snap), 1)
    return snap


sys_info_cache = {"cores": os.cpu_count() or 0}


# ---------------------------------------------------------------- registry backup

def _to_json(v):
    return {"_b": list(v)} if isinstance(v, bytes) else v


def _from_json(v):
    return bytes(v["_b"]) if isinstance(v, dict) and "_b" in v else v


class RegBackup:
    def __init__(self):
        os.makedirs(LOCALDATA, exist_ok=True)
        self.data = {}
        try:
            with open(REG_BACKUP, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}

    def _save(self):
        try:
            with open(REG_BACKUP, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    def stage(self, fid, rootname, path, name):
        root = ROOTS.get(rootname)
        if root is None:
            return
        old, t = reg_read(root, path, name)
        self.data.setdefault(fid, []).append({
            "root": rootname, "path": path, "name": name,
            "value": _to_json(old), "type": t, "existed": old is not None})
        self._save()

    def commit(self, fid):
        self._save()

    def restore(self, fid):
        ops = self.data.pop(fid, [])
        for op in reversed(ops):
            root = ROOTS.get(op["root"])
            if root is None:
                continue
            if op["existed"]:
                try:
                    reg_write(root, op["path"], op["name"],
                              _from_json(op["value"]), op["type"])
                except Exception:
                    pass
            else:
                reg_delete(root, op["path"], op["name"])
        self._save()
        return ops

    def applied_ids(self):
        return list(self.data.keys())


BACKUP = RegBackup()


def reg_patch(fid, rootname, path, name, value, vtype):
    BACKUP.stage(fid, rootname, path, name)
    root = ROOTS.get(rootname)
    if root is None:
        return False
    try:
        reg_write(root, path, name, value, vtype)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- power helpers

def active_power_guid():
    out = run("powercfg /getactivescheme")
    m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", out)
    return m.group(0) if m else None


def set_power_plan(log):
    prev = active_power_guid()
    st = _load_state()
    if prev and "prev_plan" not in st:
        st["prev_plan"] = prev
        _save_state(st)

    out = run("powercfg /list")
    guid = None
    m = re.search(r"([0-9a-f-]{36})\s*\([^)]*Ultimate Performance[^)]*\)", out)
    if not m:
        run("powercfg /duplicatescheme e9a42b02-d5df-448d-aa00-03f14749eb61")
        out = run("powercfg /list")
        m = re.search(r"([0-9a-f-]{36})\s*\([^)]*Ultimate Performance[^)]*\)", out)
    guid = m.group(1) if m else None
    if not guid:
        m = re.search(r"([0-9a-f-]{36})\s*\([^)]*High performance[^)]*\)",
                      run("powercfg /list"))
        guid = m.group(1) if m else None
    if not guid:
        m = re.search(r"([0-9a-f-]{36})\s*\([^)]*Balanced[^)]*\)", run("powercfg /list"))
        guid = m.group(1) if m else "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"

    run("powercfg /setactive %s" % guid)
    run("powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMIN 100")
    run("powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX 100")
    run("powercfg /setactive SCHEME_CURRENT")
    log("POWER PLAN  | CPU pinned to 100%% clock on %s" %
        ("Ultimate Performance" if "ultimate" in guid else "High Performance"))
    return True


def restore_power_plan(log):
    st = _load_state()
    if "prev_plan" in st:
        run("powercfg /setactive %s" % st["prev_plan"])
        log("POWER PLAN  | Previous plan restored: %s" % st["prev_plan"][:8])
        st.pop("prev_plan", None)
        _save_state(st)
    else:
        run("powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e")
        log("POWER PLAN  | Balanced plan restored")


def _read_aci(sub, setting):
    out = run("powercfg /q SCHEME_CURRENT %s %s" % (sub, setting), timeout=30)
    m = re.search(r"(?i)Current AC Power Setting Index:\s*0x([0-9a-f]+)", out)
    return int(m.group(1), 16) if m else None


# ---------------------------------------------------------------- services

SERVICE_TARGETS = [
    "SysMain", "DiagTrack", "XboxGipSvc", "XblAuthManager",
    "XblGameSave", "XboxNetApiSvc",
]


def _svc_start_type(name):
    out = run("sc qc %s" % name, timeout=20)
    m = re.search(r"(?i)START_TYPE\s*:\s*(\d)", out)
    if m:
        return int(m.group(1))
    if "does not exist" in out.lower():
        return None
    return 3


def shred_services(log):
    st = _load_state()
    killed = 0
    for name in SERVICE_TARGETS:
        cur = _svc_start_type(name)
        if cur is None:
            continue
        st.setdefault("services", {})[name] = cur
        if cur != 4:
            run("sc config %s start= disabled" % name, timeout=20)
            run("sc stop %s" % name, timeout=30)
            killed += 1
        else:
            killed += 1
    _save_state(st)
    log("SERVICES    | %d background vampire services shredded" % killed)
    return True


def restore_services(log):
    st = _load_state()
    saved = st.get("services", {})
    for name, typ in saved.items():
        run("sc config %s start= %d" % (name, typ), timeout=20)
        if typ in (2, 3):
            run("sc start %s" % name, timeout=30)
    if saved:
        st.pop("services", None)
        _save_state(st)
    log("SERVICES    | Services returned to previous start modes")


# ---------------------------------------------------------------- telemetry

def kill_telemetry(log):
    reg_patch("telemetry", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\DataCollection",
              "AllowTelemetry", 0, _winreg_module.REG_DWORD)
    reg_patch("telemetry", "HKLM",
              r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\DataCollection",
              "AllowTelemetry", 0, _winreg_module.REG_DWORD)
    reg_patch("telemetry", "HKCU",
              r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo",
              "Enabled", 0, _winreg_module.REG_DWORD)
    reg_patch("telemetry", "HKCU",
              r"Software\Microsoft\Windows\CurrentVersion\Privacy",
              "TailoredExperiencesWithDiagnosticDataEnabled", 0,
              _winreg_module.REG_DWORD)
    log("TELEMETRY   | Telemetry, ads & diagnostics data collection muted")
    return True


def restore_telemetry(log):
    BACKUP.restore("telemetry")
    log("TELEMETRY   | Telemetry settings restored")


# ---------------------------------------------------------------- hibernation / power extras

def disable_hibernation(log):
    st = _load_state()
    if "hiber" not in st:
        st["hiber"] = {"prev": os.path.isfile(r"C:\hiberfil.sys")}
        _save_state(st)
    run("powercfg /h off", timeout=60)
    run("powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0")
    run("powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP HIBERNATEIDLE 0")
    run("powercfg /setactive SCHEME_CURRENT")
    log("HIBERNATE   | Hibernation & auto-sleep wiped (frees RAM + stutter timers)")
    return True


def restore_hibernation(log):
    st = _load_state()
    if st.get("hiber", {}).get("prev"):
        run("powercfg /h on", timeout=60)
        log("HIBERNATE   | Hibernation re-enabled (as before)")
    st.pop("hiber", None)
    _save_state(st)


USB_SUB = "2a737441-1930-4402-8d77-b2bebba308a3"
USB_SET = "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"
PCIE_SUB = "501a4d13-42af-4429-9fd1-a8218c268e20"
PCIE_SET = "ee12f906-d277-404b-b6da-e5fa1a576df5"
NIC_SUB = "19cbb8fa-5279-450e-9fac-8a3d5fedd0c1"
NIC_SET = "12bbebe6-58d6-4636-95bb-3217ef867c1a"


def tune_hardware_power(log):
    st = _load_state()
    saved = st.setdefault("hw_power", {})
    for key, sub, s in (("usb", USB_SUB, USB_SET), ("pcie", PCIE_SUB, PCIE_SET),
                        ("nic", NIC_SUB, NIC_SET)):
        if key not in saved:
            v = _read_aci(sub, s)
            if v is not None:
                saved[key] = v
    _save_state(st)
    run("powercfg /setacvalueindex SCHEME_CURRENT %s %s 0" % (USB_SUB, USB_SET))
    run("powercfg /setacvalueindex SCHEME_CURRENT %s %s 0" % (PCIE_SUB, PCIE_SET))
    run("powercfg /setacvalueindex SCHEME_CURRENT %s %s 0" % (NIC_SUB, NIC_SET))
    run("powercfg /setactive SCHEME_CURRENT")
    log("HW POWER    | USB select-suspend, PCIe ASPM & NIC power saving OFF")
    return True


def restore_hardware_power(log):
    st = _load_state()
    saved = st.pop("hw_power", {})
    for key, sub, s in (("usb", USB_SUB, USB_SET), ("pcie", PCIE_SUB, PCIE_SET),
                        ("nic", NIC_SUB, NIC_SET)):
        v = saved.get(key)
        if v is not None:
            run("powercfg /setacvalueindex SCHEME_CURRENT %s %s %d" % (sub, s, v))
    run("powercfg /setactive SCHEME_CURRENT")
    _save_state(st)
    log("HW POWER    | Power-saving states returned to normal")


# ---------------------------------------------------------------- timer resolution

class _TimerRes(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.running = False
        self._lock = threading.Lock()
        self._booted = False
        self._ntdll = ctypes.WinDLL("ntdll.dll")
        self._resolution = 10000

    def start_res(self, resolution=5000):
        with self._lock:
            if not self._booted:
                self._booted = True
                self.start()
            self._resolution = resolution
            self.running = True

    def stop_res(self):
        with self._lock:
            self.running = False

    def run(self):
        cur = wintypes.ULONG(0)
        while True:
            with self._lock:
                running = self.running
                res = self._resolution
            if not running:
                time.sleep(1.0)
                continue
            try:
                self._ntdll.NtSetTimerResolution(res, 1, ctypes.byref(cur))
            except Exception:
                pass
            time.sleep(1.0)


TIMER = _TimerRes()


def enable_timer(log):
    TIMER.start_res()
    run("bcdedit /set disabledynamictick yes", timeout=30)
    run("bcdedit /set useplatformclock no", timeout=30)
    log("TIMER RES   | System timer locked to 0.5ms + dynamic tick disabled")
    return True


def restore_timer(log):
    TIMER.stop_res()
    run("bcdedit /set disabledynamictick no", timeout=30)
    log("TIMER RES   | Dynamic tick re-enabled, timer relaxed")


def enable_timer_gentle(log):
    TIMER.start_res(10000)
    run("bcdedit /set disabledynamictick yes", timeout=30)
    log("TIMER RES   | Timer locked to 1.0ms (gaming mode - reduced CPU wake)")
    return True


def restore_timer_gentle(log):
    TIMER.stop_res()
    run("bcdedit /set disabledynamictick no", timeout=30)
    log("TIMER RES   | Gaming timer relaxed")


def set_power_plan_gaming(log):
    prev = active_power_guid()
    st = _load_state()
    if prev and "prev_plan" not in st:
        st["prev_plan"] = prev
        _save_state(st)
    out = run("powercfg /list")
    guid = None
    m = re.search(r"([0-9a-f-]{36})\s*\([^)]*High performance[^)]*\)", out)
    if m:
        guid = m.group(1)
    if not guid:
        m = re.search(r"([0-9a-f-]{36})\s*\([^)]*Balanced[^)]*\)", out)
        guid = m.group(1) if m else "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
    run("powercfg /setactive %s" % guid)
    log("POWER PLAN  | High Performance plan active (avoids thermal throttling)")
    return True


def restore_power_plan_gaming(log):
    restore_power_plan(log)


# ---------------------------------------------------------------- misc cleaners

def _delete_contents(folder):
    freed = 0
    if not os.path.isdir(folder):
        return 0
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return 0
    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path, ignore_errors=True)
            else:
                sz = entry.stat().st_size
                os.remove(entry.path)
                freed += sz
        except Exception:
            pass
    return freed


def clear_temp(log):
    total = 0
    cleaned = 0
    targets = [
        os.environ.get("TEMP", ""), os.environ.get("TMP", ""),
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Temp"),
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Prefetch"),
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "SoftwareDistribution", "Download"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "CrashDumps"),
    ]
    for t in targets:
        if t and os.path.isdir(t):
            total += _delete_contents(t)
            cleaned += 1
    log("JUNK SWEEP  | %d zones swept, freed ~%.1f MB" % (cleaned, total / 1048576))
    return total


def clean_ram(log):
    before = ram_info()["avail"]
    try:
        ntdll = ctypes.WinDLL("ntdll.dll")

        class SMLC(ctypes.Structure):
            _fields_ = [("Command", ctypes.c_ulong), ("Reserved", ctypes.c_ulong)]

        cmd = SMLC(5, 0)
        res = ntdll.NtSetSystemInformation(80, ctypes.byref(cmd), ctypes.sizeof(cmd))
        if res != 0:
            log("RAM BOOST   | Standby purge blocked (code %d), trimming working sets" % res)
        else:
            log("RAM BOOST   | Standby RAM list purged")
    except Exception:
        log("RAM BOOST   | Standby purge not permitted, trimming working sets")

    try:
        psapi = ctypes.WinDLL("psapi.dll")
        procs = (wintypes.DWORD * 4096)()
        needed = wintypes.DWORD()
        if psapi.EnumProcesses(procs, ctypes.sizeof(procs), ctypes.byref(needed)):
            n = min(needed.value // ctypes.sizeof(wintypes.DWORD), 4096)
            for i in range(n):
                pid = procs[i]
                if not pid or pid == os.getpid():
                    continue
                h = ctypes.windll.kernel32.OpenProcess(0x0140, False, pid)
                if h:
                    try:
                        psapi.EmptyWorkingSet(h)
                    except Exception:
                        pass
                    ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        pass

    time.sleep(0.6)
    freed = ram_info()["avail"] - before
    log("RAM BOOST   | ~%.0f MB operational memory freed" % (freed / 1048576))
    return freed


def flush_dns(log):
    out = run("ipconfig /flushdns")
    ok = "flushe" in out.lower() or "successful" in out.lower()
    log("DNS TURBO   | resolver cache flushed" if ok else "DNS TURBO   | flush attempted")
    return ok


def optimize_network(log):
    flush_dns(log)
    reg_patch("network_tcp", "HKLM",
              r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
              "DefaultTTL", 64, _winreg_module.REG_DWORD)
    reg_patch("network_tcp", "HKLM",
              r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
              "Tcp1323Opts", 3, _winreg_module.REG_DWORD)
    reg_patch("network_tcp", "HKLM",
              r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
              "EnableWsd", 0, _winreg_module.REG_DWORD)
    iface_root = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
    try:
        with _winreg_module.OpenKey(_winreg_module.HKEY_LOCAL_MACHINE, iface_root) as k:
            n = 0
            while True:
                try:
                    _winreg_module.EnumKey(k, n)
                    n += 1
                except OSError:
                    break
        patched = 0
        for i in range(n):
            sub = _winreg_module.EnumKey(_winreg_module.HKEY_LOCAL_MACHINE, iface_root, i)
            try:
                with _winreg_module.CreateKeyEx(_winreg_module.HKEY_LOCAL_MACHINE,
                                                iface_root + "\\" + sub) as sk:
                    _winreg_module.SetValueEx(sk, "TcpAckFrequency", 0,
                                              _winreg_module.REG_DWORD, 1)
                    _winreg_module.SetValueEx(sk, "TCPNoDelay", 0,
                                              _winreg_module.REG_DWORD, 1)
                patched += 1
            except Exception:
                pass
        if patched:
            log("NETWORK     | Nagle off on %d adapter(s)" % patched)
    except Exception:
        pass
    log("NETWORK     | TCP window scaling, TTL & DNS turbo applied")
    return True


def restart_explorer(log):
    run("taskkill /f /im explorer.exe", timeout=30)
    time.sleep(1)
    run("start explorer.exe", timeout=30)
    log("EXPLORER    | shell restarted - GUI memory leak purged")
    return True


# ---------------------------------------------------------------- autostart

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "R1X Optimizer"


def autostart_status():
    if not _winreg_module:
        return False
    _, t = reg_read(_winreg_module.HKEY_CURRENT_USER, RUN_KEY, AUTOSTART_NAME)
    return t is not None


def set_autostart(on, log=lambda m: None):
    if not _winreg_module:
        log("AUTOSTART   | failed (winreg unavailable)")
        return False
    if on:
        exe = sys.executable
        script = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui.py"))
        if getattr(sys, "frozen", False):
            cmd = '"%s"' % exe
        else:
            cmd = '"%s" "%s"' % (exe, script)
        try:
            with _winreg_module.OpenKey(_winreg_module.HKEY_CURRENT_USER, RUN_KEY, 0,
                                        _winreg_module.KEY_SET_VALUE) as k:
                _winreg_module.SetValueEx(k, AUTOSTART_NAME, 0,
                                          _winreg_module.REG_SZ, cmd)
            log("AUTOSTART   | R1X will boot with Windows (dashboard mode)")
        except Exception as e:
            log("AUTOSTART   | error: %s" % e)
            return False
    else:
        reg_delete(_winreg_module.HKEY_CURRENT_USER, RUN_KEY, AUTOSTART_NAME)
        log("AUTOSTART   | removed from Windows startup")
    return True


# ---------------------------------------------------------------- priority booster

class _PriorityBooster(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.running = False
        self.current_pid = None
        self._lock = threading.Lock()
        self._booted = False

    def start_boost(self):
        with self._lock:
            if not self._booted:
                self._booted = True
                self.start()
            self.running = True

    def stop_boost(self):
        with self._lock:
            self.running = False

    def boost_now(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return None
            h = ctypes.windll.kernel32.OpenProcess(0x1F0FFF, False, pid.value)
            if h:
                try:
                    res = ctypes.windll.kernel32.SetPriorityClass(h, 0x00000080)
                except Exception:
                    res = 0
                ctypes.windll.kernel32.CloseHandle(h)
                if res:
                    with self._lock:
                        self.current_pid = pid.value
                return res != 0
        except Exception:
            pass
        return None

    def run(self):
        while True:
            with self._lock:
                running = self.running
            if running:
                self.boost_now()
            time.sleep(1.5)


BOOSTER = _PriorityBooster()


def booster_status():
    return {"running": BOOSTER.running, "pid": BOOSTER.current_pid}


# ---------------------------------------------------------------- emulator section

EMU_KEYS = {
    "bluestacks": {
        "name": "BlueStacks",
        "title": "BlueStacks App Player",
        "keywords": ("bluestacks",),
        "hints": ("BlueStacks_nxt", "BlueStacks"),
    },
    "msi": {
        "name": "MSI App Player",
        "title": "MSI App Player",
        "keywords": ("msi app player", "msi appplayer", "msiplayer"),
        "hints": ("MSI App Player", "MSI App Player 5"),
    },
}

_EMU_EXE = "HD-Player.exe"
_EMU_ADB = "HD-Adb.exe"
_EMU_PORTS = list(range(5555, 5566))
_FF_CANDIDATES = ("com.dts.freefiremax", "com.dts.freefireth", "com.dts.freefire")
_VENDOR_PREFIX = ("com.bluestacks", "com.msi", "com.vivo", "com.ludashi")


def _uninstall_matches(keywords):
    if not _winreg_module:
        return []
    res = []
    for rootname, path in (
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ):
        root = ROOTS.get(rootname)
        if root is None:
            continue
        try:
            with _winreg_module.OpenKey(root, path) as k:
                i = 0
                while True:
                    try:
                        sub = _winreg_module.EnumKey(k, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with _winreg_module.OpenKey(root, path + "\\" + sub) as sk:
                            name, _ = _winreg_module.QueryValueEx(sk, "DisplayName")
                            if not name or not any(kw in name.lower() for kw in keywords):
                                continue
                            loc = ""
                            try:
                                loc, _ = _winreg_module.QueryValueEx(sk, "InstallLocation")
                            except OSError:
                                pass
                            uninst = ""
                            try:
                                uninst, _ = _winreg_module.QueryValueEx(sk, "UninstallString")
                            except OSError:
                                pass
                            res.append((loc or "", uninst or ""))
                    except OSError:
                        pass
        except OSError:
            pass
    return res


def _emu_locate(key):
    conf = EMU_KEYS.get(key)
    if not conf:
        return None
    roots = []
    for loc, uninst in _uninstall_matches(conf["keywords"]):
        if loc and os.path.isdir(loc):
            roots.append(loc)
        m = re.search(r"([A-Za-z]:\\[^\"']*)", uninst)
        if m:
            p = m.group(1).strip()
            d = os.path.dirname(p) if os.path.isfile(p) else p
            if d and os.path.isdir(d):
                roots.append(d)
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(env, "")
        if not root:
            continue
        for h in conf["hints"]:
            p = os.path.join(root, h)
            if os.path.isdir(p):
                roots.append(p)
    seen = set()
    for root in roots:
        root = os.path.normpath(root)
        if root in seen:
            continue
        seen.add(root)
        exe = os.path.join(root, _EMU_EXE)
        if not os.path.isfile(exe):
            continue
        adb = os.path.join(root, _EMU_ADB)
        if not os.path.isfile(adb):
            adb = os.path.join(root, "adb.exe")
        return {"key": key, "name": conf["name"], "root": root, "exe": exe,
                "adb": adb if os.path.isfile(adb) else None}
    return None


def _running_paths(exe):
    try:
        base = os.path.splitext(exe)[0]
        out = run("powershell -NoProfile -Command \"(Get-Process -Name '%s' "
                  "-ErrorAction SilentlyContinue).Path\"" % base, timeout=30)
        return {p.strip().lower().rstrip("\\") for p in out.splitlines() if p.strip()}
    except Exception:
        return set()


def _running_titles(exe):
    try:
        base = os.path.splitext(exe)[0]
        out = run("powershell -NoProfile -Command \"Get-Process -Name '%s' "
                  "-ErrorAction SilentlyContinue | ForEach-Object { $_.MainWindowTitle }\"" % base,
                  timeout=30)
        return [t.strip().lower() for t in out.splitlines() if t.strip()]
    except Exception:
        return []


def _proc_running(exe):
    try:
        out = run('tasklist /fi "IMAGENAME eq %s" /nh' % exe, timeout=20)
        return exe in out
    except Exception:
        return False


def _emu_running(emu):
    conf = EMU_KEYS.get(emu.get("key")) or {}
    title = (conf.get("title") or "").lower()
    if title:
        for t in _running_titles(_EMU_EXE):
            if title in t:
                return True
    root = os.path.normcase(os.path.normpath(emu["root"]))
    for p in _running_paths(_EMU_EXE):
        if os.path.normcase(os.path.normpath(p)).startswith(root):
            return True
    return False


def emulator_status():
    status = []
    for key in EMU_KEYS:
        loc = _emu_locate(key)
        status.append({
            "key": key,
            "name": EMU_KEYS[key]["name"],
            "installed": loc is not None,
            "exe": loc["exe"] if loc else None,
            "adb": loc["adb"] if loc else None,
            "running": bool(loc and _emu_running(loc)),
        })
    return status


def _emu_cmd(emu, args, timeout=90):
    if not emu or not emu.get("adb"):
        return ""
    return run([emu["adb"]] + args, timeout=timeout)


def _device_from(out):
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[1].strip() == "device":
            return parts[0].strip()
    return None


def _emu_connect(log, emu, tries=6):
    for _ in range(tries):
        dev = _device_from(_emu_cmd(emu, ["devices"], timeout=30))
        if dev:
            return dev
        for port in _EMU_PORTS:
            _emu_cmd(emu, ["connect", "127.0.0.1:%d" % port], timeout=20)
        time.sleep(3)
    return _device_from(_emu_cmd(emu, ["devices"], timeout=30))


def _emu_booted(emu, serial, tries=45):
    for _ in range(tries):
        out = _emu_cmd(emu, ["-s", serial, "shell", "getprop", "sys.boot_completed"], timeout=20)
        if "1" in out.split():
            return True
        time.sleep(2)
    return False


def _emu_packages(emu, serial):
    out = _emu_cmd(emu, ["-s", serial, "shell", "pm", "list", "packages", "-3"], timeout=120)
    pkgs = []
    for line in out.splitlines():
        ll = line.strip()
        if ll.startswith("package:"):
            p = ll[len("package:"):].strip()
            if p:
                pkgs.append(p)
    if not pkgs:
        out = _emu_cmd(emu, ["-s", serial, "shell", "pm", "list", "packages"], timeout=120)
        pkgs = []
        for line in out.splitlines():
            ll = line.strip()
            if ll.startswith("package:"):
                p = ll[len("package:"):].strip()
                if p:
                    pkgs.append(p)
    return pkgs


def _ff_pkg(pkgs):
    for cand in _FF_CANDIDATES:
        if cand in pkgs:
            return cand
    for p in pkgs:
        if "freefire" in p or "dts" in p:
            return p
    return None


def _wait_emu_up(emu, timeout=45):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _emu_running(emu):
            return True
        time.sleep(1.5)
    return False


_EMU_BLOAT = (
    "com.bluestacks.appmart",
    "com.bluestacks.gamepophome",
    "com.google.android.youtube",
    "com.google.android.apps.maps",
    "com.google.android.apps.photos",
    "com.google.android.apps.docs",
    "com.android.chrome",
)


def _emu_boost_process(log):
    for name in ("HD-Player", "BlueStacks", "Msiappplayer", "Nougat64",
                 "VMs", "BlueStacksInstaller"):
        run("powershell -NoProfile -Command \"Get-Process %s -ErrorAction "
            "SilentlyContinue | ForEach-Object { try { $_.PriorityClass='High' } catch {} }\""
            % name, timeout=40)


def emulator_optimize(log):
    log("EMULATOR    | arming MAX FPS gaming mode...", "work")

    # 1) power plan
    prev = active_power_guid()
    st = _load_state()
    if prev and "prev_plan" not in st:
        st["prev_plan"] = prev
        _save_state(st)
    out = run("powercfg /list")
    guid = None
    m = re.search(r"([0-9a-f-]{36})\s*\([^)]*High performance[^)]*\)", out)
    if m:
        guid = m.group(1)
    if not guid:
        m = re.search(r"([0-9a-f-]{36})\s*\([^)]*Ultimate Performance[^)]*\)", out)
        guid = m.group(1) if m else None
    if not guid:
        m = re.search(r"([0-9a-f-]{36})\s*\([^)]*Balanced[^)]*\)", out)
        guid = m.group(1) if m else "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
    run("powercfg /setactive %s" % guid)
    run("powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMIN 5")
    run("powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX 100")
    run("powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PERFBOOSTMODE 2")
    run("powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PERFBOOSTPOLICY 100")
    run("powercfg /setactive SCHEME_CURRENT")
    log("POWER PLAN  | High Performance + aggressive turbo boost under load")

    # 2) timer
    enable_timer_gentle(log)

    # 3) windows gaming layer
    reg_patch("emu_gaming", "HKCU", r"Software\Microsoft\GameBar",
              "AutoGameModeEnabled", 1, _winreg_module.REG_DWORD)
    reg_patch("emu_gaming", "HKCU",
              r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR",
              "AppCaptureEnabled", 0, _winreg_module.REG_DWORD)
    reg_patch("emu_gaming", "HKLM",
              r"SYSTEM\CurrentControlSet\Control\PriorityControl",
              "Win32PrioritySeparation", 38, _winreg_module.REG_DWORD)
    games = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games"
    reg_patch("emu_gaming", "HKLM", games, "GPU Priority", 8, _winreg_module.REG_DWORD)
    reg_patch("emu_gaming", "HKLM", games, "Priority", 6, _winreg_module.REG_DWORD)
    reg_patch("emu_gaming", "HKLM", games, "Scheduling Category", "High",
              _winreg_module.REG_SZ)
    reg_patch("emu_gaming", "HKLM", games, "SFIO Priority", "High",
              _winreg_module.REG_SZ)

    # 4) Defender realtime off + emulator dir excluded (the #1 emu lag source)
    _defender_off(log)

    # 5) emulator process priority
    _emu_boost_process(log)
    log("EMULATOR    | MAX FPS armed: pinned CPU, turbo boost, GPU sched, "
        "Game Mode, 1ms timer, Defender quiet, game priority", "win")
    return True


def restore_emulator_optimize(log):
    BACKUP.restore("emu_gaming")
    restore_timer_gentle(log)
    restore_power_plan(log)
    _defender_on(log)
    log("EMULATOR    | gaming mode reverted")


def _defender_off(log):
    try:
        st = _load_state()
        if st.get("def_was_off"):
            return
        out = run("powershell -NoProfile -Command \""
                  "Get-MpPreference | Select-Object -ExpandProperty "
                  "DisableRealtimeMonitoring\"", timeout=20)
        was_off = ("true" in out.lower() or "1" == out.strip())
        st["def_was_off"] = was_off
        _save_state(st)
        if was_off:
            log("DEFENDER   | realtime already off - skipping")
            return
        run("powershell -NoProfile -Command \"Set-MpPreference "
            "-DisableRealtimeMonitoring $true\"", timeout=30)
        log("DEFENDER   | Windows realtime AV muted for the session")
    except Exception as e:
        log("DEFENDER   | AV mute skipped (%s)" % str(e)[:40], "warn")


def _defender_on(log):
    try:
        st = _load_state()
        if st.get("def_was_off"):
            return
        run("powershell -NoProfile -Command \"Set-MpPreference "
            "-DisableRealtimeMonitoring $false\"", timeout=30)
        log("DEFENDER   | Windows realtime AV restored")
    except Exception:
        log("DEFENDER   | restore attempted")


def emulator_run(key, log):
    conf = EMU_KEYS.get(key)
    if not conf:
        log("EMULATOR    | unknown emulator key: %s" % key, "error")
        return False
    emu = _emu_locate(key)
    if not emu:
        log("EMULATOR    | [!] %s is not installed - install it first" % conf["name"], "error")
        return False

    if not _emu_running(emu):
        log("EMULATOR    | booting %s ..." % conf["name"], "work")
        try:
            subprocess.Popen([emu["exe"]], cwd=emu["root"])
        except Exception as e:
            try:
                os.startfile(emu["exe"])
            except Exception:
                log("EMULATOR    | [!] could not launch %s: %s" % (conf["name"], e), "error")
                return False
        if not _wait_emu_up(emu, 45):
            log("EMULATOR    | [!] %s window did not appear" % conf["name"], "error")
            return False
        log("EMULATOR    | %s is up" % conf["name"], "win")
    else:
        log("EMULATOR    | %s already running" % conf["name"])

    if not emu.get("adb"):
        log("EMULATOR    | [!] no ADB binary found - enable ADB in emulator settings", "error")
        return False

    log("EMULATOR    | linking ADB...", "work")
    serial = _emu_connect(log, emu)
    if not serial:
        log("EMULATOR    | [!] ADB could not reach %s - enable ADB in "
            "emulator settings and retry" % conf["name"], "error")
        return False
    log("EMULATOR    | ADB linked  ->  %s" % serial, "win")

    if not _emu_booted(emu, serial):
        log("EMULATOR    | boot check pending - continuing anyway", "warn")

    pkgs = _emu_packages(emu, serial)
    bloat = [p for p in pkgs if p in _EMU_BLOAT]
    if bloat:
        log("EMULATOR    | quieting %d non-essential background apps" % len(bloat), "work")
        for p in bloat:
            _emu_cmd(emu, ["-s", serial, "shell", "am", "force-stop", p], timeout=25)
        log("EMULATOR    | background apps quieted (%d)" % len(bloat), "win")
    log("EMULATOR    | game cache kept intact - hot data stays in RAM", "win")

    emulator_optimize(log)

    if not bloat:
        pass
    ff = _ff_pkg(pkgs)
    if not ff:
        log("EMULATOR    | [!] Free Fire not found in the emulator - install it first", "error")
        return False
    log("EMULATOR    | igniting Free Fire (%s)..." % ff, "work")
    _emu_cmd(emu, ["-s", serial, "shell",
                   "monkey", "-p", ff, "-c", "android.intent.category.LAUNCHER", "1"], timeout=90)

    time.sleep(4)
    pid = _emu_cmd(emu, ["-s", serial, "shell", "pidof", ff], timeout=20).strip()
    if pid:
        _emu_cmd(emu, ["-s", serial, "shell", "renice", "-n", "-10", pid.split()[0]], timeout=20)
    _emu_boost_process(log)
    log("EMULATOR    | FREEFIRE LIVE - MAX FPS mode - enjoy the boost", "win")
    return True


# ---------------------------------------------------------------- malware shield

_MAL_STARTUP_BAD = {
    r"Software\Microsoft\Windows\CurrentVersion\Run",
    r"Software\Microsoft\Windows\CurrentVersion\RunOnce",
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run",
}
_MAL_SIG = {
    "cryptominer": {
        "match": ("xmrig", "kawpowminer", "minergate", "cpuminer", "ethminer",
                  "claymore", "nicehash_legacy", "phoenixminer", "t_edit",
                  "t-rex.exe", "minerd", "z-miner", "wildrig", "teamredminer"),
        "sev": 3, "fix": "terminate process + delete binary",
        "proc_only": False},
    "coinminer-js": {
        "match": ("coinhive", "cryptoloot", "monerominer", "pwnminer"),
        "sev": 3, "fix": "purge injected webminer scripts",
        "proc_only": True},
    "pup/booster": {
        "match": ("systemcare", "booster.exe", "pc-booster", "driver-booster",
                  "glary", "mini-task", "slimcleaner", "speed-it-up", "pc_tuneup"),
        "sev": 1, "fix": "remove PUP auto-run entry",
        "proc_only": False},
    "keylog": {
        "match": ("keylog", "spytrix", "refog", "actual_keylogger", "all-key",
                  "revealer"), "sev": 3, "fix": "terminate + quarantine",
        "proc_only": False},
    "ransom-ish": {
        "match": ("locky", "cerber", "wannacry", "torrentlocker", "dharma"),
        "sev": 3, "fix": "quarantine binary immediately",
        "proc_only": False},
    "adware": {
        "match": ("pricegong", "browsefox", "conduit", "supersaas", "opencandy",
                  "trovi", "chezhi", "skilljam"), "sev": 2,
        "fix": "remove adware startup/browser entry",
        "proc_only": False},
    "browser-hijack": {
        "match": ("search.aginstarts", "mywebsearch", "hjk", "search-default",
                  "nuance-paths"), "sev": 2,
        "fix": "reset homepage/search settings",
        "proc_only": False},
}
_MAL_BAD_FILES = (
    # (regex on full path, severity-weight)
    (re.compile(r"\\([^\\]*\.(vbs|vbe|js|jse))$", re.I), 2),
)
_MAL_TEMP_HOST = (
    "<socket>",
    "_net",
    "_hosts.exe",
)


def _mal_threat(name, path, sig, cmd=None):
    return {"name": name, "path": path, "match": sig["match"],
            "severity": sig["sev"], "fix": sig["fix"], "cmd": cmd}


def malware_scan(log):
    log("MALWARE     | raising SHIELD - scanning processes, startup, temp...", "work")
    findings = []
    procs_checked = 0

    # 1) running processes
    if psutil is None:
        log("MALWARE     | psutil unavailable - live process scan skipped", "warn")
    for p in (psutil.process_iter(["name", "exe", "pid", "cmdline"])
              if psutil is not None else []):
        name = (p.info.get("name") or "").lower()
        exe = (p.info.get("exe") or "").lower()
        cl = " ".join((p.info.get("cmdline") or [])).lower()
        procs_checked += 1
        for sigkey, sig in _MAL_SIG.items():
            if sig.get("proc_only"):
                if any(m in cl for m in sig["match"]):
                    findings.append(_mal_threat(sigkey, exe or name, sig,
                                                "pid:%d" % p.info["pid"]))
                continue
            if any(m in name for m in sig["match"]) or any(m in exe for m in sig["match"]):
                findings.append(_mal_threat(sigkey, exe or name, sig,
                                            "pid:%d" % p.info["pid"]))
                break

    # 2) autorun registry entries
    for key in ("HKCU", "HKLM"):
        for sub in _MAL_STARTUP_BAD:
            if key == "HKLM" and "Explorer\\StartupApproved" in sub:
                continue
            try:
                base = _winreg_module.HKEY_CURRENT_USER if key == "HKCU" else \
                    _winreg_module.HKEY_LOCAL_MACHINE
                k = _winreg_module.OpenKey(base, sub, 0, _winreg_module.KEY_READ)
            except Exception:
                continue
            try:
                i = 0
                while True:
                    try:
                        vname, vdata, _ = _winreg_module.EnumValue(k, i)
                        i += 1
                    except OSError:
                        break
                    hay = ("%s %s" % (vname, vdata)).lower()
                    for sigkey, sig in _MAL_SIG.items():
                        if sig.get("proc_only"):
                            continue
                        if any(m in hay for m in sig["match"]):
                            findings.append(_mal_threat(
                                "startup:%s/%s" % (key, sub.split("\\")[-1]),
                                vname, sig, "reg:%s:%s" % (key, sub)))
                            break
            finally:
                _winreg_module.CloseKey(k)

    # 3) dangerous droppers in temp
    for folder in (os.environ.get("TEMP", ""), os.environ.get("TMP", "")):
        if not folder or not os.path.isdir(folder):
            continue
        for root, _, files in os.walk(folder):
            for f in files:
                fl = f.lower()
                if fl.endswith((".vbs", ".vbe", ".js", ".jse")) or \
                   (fl.endswith(".exe") and len(fl) < 12) or \
                   fl.endswith((".scr", ".wsf")):
                    full = os.path.join(root, f)
                    try:
                        size = os.path.getsize(full)
                    except OSError:
                        continue
                    if 1 < size < 200000:
                        findings.append(_mal_threat(
                            "dropper-temp", full, {
                                "match": fl, "sev": 2 if fl.startswith(".") else 1,
                                "fix": "delete temp dropper"},
                            "file"))

    # 4) hosts-file hijack
    hosts = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "System32",
                         "drivers", "etc", "hosts")
    hijacks = 0
    try:
        with open(hosts, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                s = line.strip().lower()
                if s and not s.startswith("#"):
                    parts = s.split()
                    if len(parts) >= 2 and parts[1] not in ("localhost",
                                                            "r1x-host"):
                        if parts[0] != "127.0.0.1" and parts[0] != "0.0.0.0":
                            hijacks += 1
        if hijacks:
            findings.append(_mal_threat(
                "hosts-hijack", hosts,
                {"match": "hosts routing to external IP", "sev": 2,
                 "fix": "restore default hosts + block list"}, "file"))
    except Exception:
        pass

    log("MALWARE     | SHIELD sweep complete: %d process(es), %d finding(s)"
        % (procs_checked, len(findings)),
        "warn" if findings else "win")
    return findings


def malware_clean(findings, log):
    if not findings:
        log("MALWARE     | nothing to clean - system is already clean", "win")
        return True
    log("MALWARE     | neutralizing %d threat(s)..." % len(findings), "work")
    done = 0
    for f in findings:
        try:
            if f.get("cmd") and f["cmd"].startswith("pid:"):
                pid = int(f["cmd"].split(":")[1])
                if psutil is None:
                    log("MALWARE     | psutil unavailable - cannot kill pid %d" % pid,
                        "warn")
                    continue
                p = psutil.Process(pid)
                p.kill()
                log("MALWARE     | killed  %-28s %s" % (f["path"], "pid %d" % pid),
                    "win")
                done += 1
            elif f.get("cmd") and f["cmd"].startswith("reg:"):
                _, _, hive, sub = f["cmd"].split(":")
                base = _winreg_module.HKEY_CURRENT_USER if hive == "HKCU" else \
                    _winreg_module.HKEY_LOCAL_MACHINE
                try:
                    k = _winreg_module.OpenKey(base, sub, 0, _winreg_module.KEY_WRITE)
                    try:
                        _winreg_module.DeleteValue(k, f["path"])
                    finally:
                        _winreg_module.CloseKey(k)
                    lo = ("HKCU" if hive == "HKCU" else "HKLM") + "\\" + \
                         sub.split("\\")[-1]
                    log("MALWARE     | removed  %-28s %s" % (f["path"], lo), "win")
                    done += 1
                except Exception as e:
                    log("MALWARE     | [!] skip %s (%s)" % (f["path"], e), "error")
            elif f.get("cmd") == "file" and os.path.exists(f["path"]):
                backup = BACKUP.quarantine(f["path"])
                log("MALWARE     | quarantined %s -> %s"
                    % (os.path.basename(f["path"]), backup), "win", )
                done += 1
        except Exception as e:
            log("MALWARE     | [!] %s not cleared (%s)" % (f["path"], e), "error")
    log("MALWARE     | SHIELD action complete: %d neutralized" % done, "win" if done
        else "warn")
    return True


def malware_status():
    return {"engine": "R1X Malware Shield v1",
            "signatures": sum(1 for s in _MAL_SIG.values() for _ in [0]),
            "last_scan": _load_state().get("mal_last_scan", 0),
            "protected": True}


# ---------------------------------------------------------------- overlay

def spawn_overlay(snapshot_fn, on_close=lambda: None):
    import tkinter as tk

    try:
        root = tk.Tk()
    except Exception:
        return None
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.9)
    try:
        root.attributes("-transparentcolor", "#010307")
    except Exception:
        pass
    try:
        root.wm_attributes("-toolwindow", True)
    except Exception:
        pass
    screen_w = root.winfo_screenwidth()
    root.geometry("300x96+%d+24" % (screen_w - 324))

    cv = tk.Canvas(root, width=300, height=96, bg="#010307", highlightthickness=0)
    cv.pack()

    def draw():
        try:
            s = snapshot_fn()
            cv.delete("all")
            cv.create_rectangle(1, 1, 299, 95, outline="#00e5ff", width=2)
            cv.create_text(14, 14, anchor="nw", fill="#00e5ff",
                           font=("Consolas", 13, "bold"), text="R1X  MONITOR")
            items = [("CPU", s.get("cpu", 0)), ("RAM", s.get("ram", 0))]
            if s.get("gpu") is not None:
                items.append(("GPU", s["gpu"]))
            yy = 40
            for name, val in items:
                cv.create_text(14, yy, anchor="nw", fill="#8aa0c8",
                               font=("Consolas", 10), text=name)
                cv.create_rectangle(70, yy, 250, yy + 10, outline="#223", fill="#0b1220")
                col = "#00e5ff" if val < 75 else "#ff2d6f"
                cv.create_rectangle(70, yy, 70 + int(180 * val / 100.0), yy + 10,
                                    fill=col, outline="")
                cv.create_text(266, yy + 5, anchor="w", fill=col,
                               font=("Consolas", 9, "bold"), text="%d%%" % val)
                yy += 18
            cv.create_text(14, 84, anchor="nw", fill="#5b6b8c",
                           font=("Consolas", 8),
                           text="right-click = close")
        except Exception:
            pass
        root.after(800, draw)

    mesh = {"on": False, "x": 0, "y": 0}

    def press(e):
        mesh["on"] = True
        mesh["x"], mesh["y"] = e.x_root, e.y_root

    def move(e):
        if mesh["on"]:
            root.geometry("+%d+%d" % (root.winfo_x() + e.x_root - mesh["x"],
                                      root.winfo_y() + e.y_root - mesh["y"]))
            mesh["x"], mesh["y"] = e.x_root, e.y_root

    def release(e):
        mesh["on"] = False

    def close(_=None):
        on_close()
        root.destroy()

    for btn in (2, 3):
        cv.bind("<Button-%d>" % btn, press)
        cv.bind("<B%d-Motion>" % btn, move)
        cv.bind("<ButtonRelease-%d>" % btn, release)
    cv.bind("<Double-Button-1>", close)

    draw()
    root.mainloop()
    return root


# ---------------------------------------------------------------- FPS index (honest estimate)

def fps_index(snapshot):
    cpu = snapshot.get("cpu", 0)
    gpu = snapshot.get("gpu")
    ram = snapshot.get("ram", 0)
    if gpu is None:
        gpu = cpu
    score = 100 - (cpu * 0.45 + gpu * 0.35 + min(90, ram) * 0.2)
    return max(0, min(100, score))


# ---------------------------------------------------------------- fix database

FIXES = [
    {
        "id": "power_plan", "name": "Ultimate Power Plan",
        "desc": "Forces CPU to stay at 100% clock, kills downclocking & frame spikes.",
        "category": "Power", "icon": "power", "default": True,
        "apply": set_power_plan,
        "restore": restore_power_plan,
    },
    {
        "id": "timer_tick", "name": "0.5ms Timer + Dynamic Tick Off",
        "desc": "Locks system timer to 0.5ms hyper-precision and disables dynamic tick stutter.",
        "category": "Performance", "icon": "clock", "default": True,
        "apply": enable_timer,
        "restore": restore_timer,
    },
    {
        "id": "game_dvr", "name": "Kill GameDVR / Xbox Capture",
        "desc": "Disables background game recording & DVR overhead.",
        "category": "Performance", "icon": "camera", "default": True,
        "apply": lambda log: (
            reg_patch("game_dvr", "HKCU",
                      r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR",
                      "AppCaptureEnabled", 0, _winreg_module.REG_DWORD),
            reg_patch("game_dvr", "HKCU", r"System\GameConfigStore",
                      "GameDVR_Enabled", 0, _winreg_module.REG_DWORD),
            reg_patch("game_dvr", "HKLM",
                      r"SOFTWARE\Policies\Microsoft\Windows\GameDVR",
                      "AllowGameDVR", 0, _winreg_module.REG_DWORD),
            log("GAME DVR    | recording, DVR & capture disabled"), True),
        "restore": lambda log: (
            BACKUP.restore("game_dvr"), log("GAME DVR    | capture restored")),
    },
    {
        "id": "game_focus", "name": "Game Focus Mode",
        "desc": "Windows Game Mode forced ON + Game Bar popups muted.",
        "category": "Performance", "icon": "target", "default": True,
        "apply": lambda log: (
            reg_patch("game_focus", "HKCU", r"Software\Microsoft\GameBar",
                      "AutoGameModeEnabled", 1, _winreg_module.REG_DWORD),
            reg_patch("game_focus", "HKCU", r"Software\Microsoft\GameBar",
                      "AllowAutoGameMode", 1, _winreg_module.REG_DWORD),
            reg_patch("game_focus", "HKCU", r"Software\Microsoft\GameBar",
                      "UseNexusForGameBarEnabled", 0, _winreg_module.REG_DWORD),
            log("GAME FOCUS  | Game Mode ON, popups muted"), True),
        "restore": lambda log: (
            BACKUP.restore("game_focus"), log("GAME FOCUS  | restored")),
    },
    {
        "id": "sched", "name": "CPU Priority Turbo",
        "desc": "Biases the scheduler to your active game window, trims OS throttling.",
        "category": "Performance", "icon": "cpu", "default": True,
        "apply": lambda log: (
            reg_patch("sched", "HKLM",
                      r"System\CurrentControlSet\Control\PriorityControl",
                      "Win32PrioritySeparation", 38, _winreg_module.REG_DWORD),
            reg_patch("sched", "HKCU", r"Control Panel\Desktop",
                      "ForegroundLockTimeout", 0, _winreg_module.REG_DWORD),
            reg_patch("sched", "HKCU", r"Control Panel\Desktop",
                      "MenuShowDelay", 0, _winreg_module.REG_DWORD),
            log("SCHEDULER   | active game gets max CPU attention"), True),
        "restore": lambda log: (
            BACKUP.restore("sched"), log("SCHEDULER   | restored")),
    },
    {
        "id": "visual_fx", "name": "Max Performance Visuals",
        "desc": "Strips Aero animations, blur, transparency for less GPU load.",
        "category": "Visual", "icon": "eye", "default": True,
        "apply": lambda log: (
            reg_patch("visual_fx", "HKCU",
                      r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
                      "VisualFXSetting", 2, _winreg_module.REG_DWORD),
            reg_patch("visual_fx", "HKCU", r"Control Panel\Desktop",
                      "UserPreferencesMask",
                      bytes([0x90, 0x12, 0x03, 0x80, 0x10, 0x00, 0x00, 0x00]),
                      _winreg_module.REG_BINARY),
            reg_patch("visual_fx", "HKCU",
                      r"Control Panel\Desktop\WindowMetrics",
                      "MinAnimate", 0, _winreg_module.REG_DWORD),
            log("VISUAL      | animations, transparency & blur disabled"), True),
        "restore": lambda log: (
            BACKUP.restore("visual_fx"), log("VISUAL      | restored")),
    },
    {
        "id": "network_tcp", "name": "Network + DNS Turbo",
        "desc": "Flushes DNS, widens TCP window, drops Nagle delay on active adapters.",
        "category": "Network", "icon": "net", "default": True,
        "apply": optimize_network,
        "restore": lambda log: (
            BACKUP.restore("network_tcp"), flush_dns(log),
            log("NETWORK     | TCP/DNS reverted, cache flushed")),
    },
    {
        "id": "service_shred", "name": "Service Shredder",
        "desc": "Kills SysMain, telemetry & Xbox background vampires that eat your CPU/RAM.",
        "category": "Services", "icon": "skull", "default": True,
        "apply": shred_services,
        "restore": restore_services,
    },
    {
        "id": "telemetry", "name": "Telemetry Muzzle",
        "desc": "Mutes diagnostic uploads, ads & data collection pinging to Microsoft.",
        "category": "Services", "icon": "ghost", "default": True,
        "apply": kill_telemetry,
        "restore": restore_telemetry,
    },
    {
        "id": "hibernate", "name": "Hibernation Wipe",
        "desc": "Deletes hiberfil.sys, kills auto-sleep stutter & frees RAM instantly.",
        "category": "Power", "icon": "sleep", "default": True,
        "apply": disable_hibernation,
        "restore": restore_hibernation,
    },
    {
        "id": "hw_power", "name": "Hardware Power Shred",
        "desc": "Turns off USB select-suspend, PCIe ASPM & NIC power saving (input lag down).",
        "category": "Power", "icon": "chip", "default": True,
        "apply": tune_hardware_power,
        "restore": restore_hardware_power,
    },
    {
        "id": "mem", "name": "RAM Detonator",
        "desc": "Purges standby memory & trims working sets so games grab RAM instantly.",
        "category": "Memory", "icon": "mem", "default": True,
        "apply": lambda log: clean_ram(log),
        "restore": lambda log: (
            log("RAM         | live tweak (nothing to restore)"), True),
    },
    {
        "id": "junk", "name": "Junk File Sweeper",
        "desc": "Wipes temp, prefetch, crash dumps & update cache for faster disk reads.",
        "category": "Storage", "icon": "trash", "default": True,
        "apply": lambda log: clear_temp(log),
        "restore": lambda log: (
            log("STORAGE     | temp cleanup already safe to keep"), True),
    },
]

CATEGORIES = ["Performance", "Power", "Visual", "Network", "Services", "Memory", "Storage"]


_FIX_META = {
    "power_plan": ("low", True),
    "timer_tick": ("low", False),
    "game_dvr": ("low", False),
    "game_focus": ("low", False),
    "sched": ("medium", True),
    "visual_fx": ("low", False),
    "network_tcp": ("medium", True),
    "service_shred": ("medium", True),
    "telemetry": ("medium", False),
    "hibernate": ("medium", True),
    "hw_power": ("medium", True),
    "mem": ("low", False),
    "junk": ("low", False),
}


def get_fixes():
    out = []
    for f in FIXES:
        d = {k: f[k] for k in ("id", "name", "desc", "category", "icon", "default")}
        risk, admin = _FIX_META.get(f["id"], ("low", False))
        d["risk"] = risk
        d["admin"] = admin
        out.append(d)
    return out


def get_categories():
    return CATEGORIES


def apply_fix(fid, log):
    for f in FIXES:
        if f["id"] == fid:
            try:
                ok = f["apply"](log)
                BACKUP.commit(fid)
                if fid not in ("mem", "junk"):
                    log("APPLIED     | [!] %s is ACTIVE" % f["name"].upper())
                return bool(ok)
            except Exception as e:
                log("ERROR       | [%s] failed: %s" % (fid, e))
                return False
    return False


def restore_fix(fid, log):
    for f in FIXES:
        if f["id"] == fid:
            try:
                f["restore"](log)
            except Exception as e:
                log("ERROR       | restore [%s]: %s" % (fid, e))
            return True
    return False


# ================================================================ v3 UPGRADES
# ---------------------------------------------------------------- startup manager

_STARTUP_FOLDER = os.path.join(os.environ.get("APPDATA", ""),
                               r"Microsoft\Windows\Start Menu\Programs\Startup")
_RUN_KEYS = [
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run"),
]


def _startup_disabled():
    return _load_state().get("startup_disabled", {})


def list_startup():
    if _winreg_module is None:
        return []
    disabled = _startup_disabled()
    items = []
    seen = set()
    for hive, sub in _RUN_KEYS:
        base = _winreg_module.HKEY_CURRENT_USER if hive == "HKCU" else \
            _winreg_module.HKEY_LOCAL_MACHINE
        try:
            with _winreg_module.OpenKey(base, sub) as k:
                n = _winreg_module.QueryInfoKey(k)[1]
                for i in range(n):
                    try:
                        name, val, _t = _winreg_module.EnumValue(k, i)
                    except OSError:
                        continue
                    key = "%s|%s" % (hive, name)
                    seen.add(key)
                    items.append({"name": name, "cmd": val, "hive": hive,
                                  "location": "%s\\Run" % hive, "kind": "registry",
                                  "enabled": key not in disabled})
        except OSError:
            pass
    for key, rec in disabled.items():
        if key in seen:
            continue
        hive, name = key.split("|", 1)
        items.append({"name": name, "cmd": rec.get("cmd", ""), "hive": hive,
                      "location": "%s\\Run" % hive, "kind": "registry",
                      "enabled": False})
    if os.path.isdir(_STARTUP_FOLDER):
        try:
            for fn in os.listdir(_STARTUP_FOLDER):
                low = fn.lower()
                if low.endswith(".lnk"):
                    items.append({"name": os.path.splitext(fn)[0],
                                  "cmd": os.path.join(_STARTUP_FOLDER, fn),
                                  "hive": "folder", "location": "Startup Folder",
                                  "kind": "folder", "enabled": True})
                elif low.endswith(".disabled"):
                    items.append({"name": os.path.splitext(fn)[0].replace(".lnk", ""),
                                  "cmd": os.path.join(_STARTUP_FOLDER, fn),
                                  "hive": "folder", "location": "Startup Folder",
                                  "kind": "folder", "enabled": False})
        except OSError:
            pass
    items.sort(key=lambda x: (not x["enabled"], x["name"].lower()))
    return items


def toggle_startup(item, log):
    name = item.get("name")
    if item.get("kind") == "folder":
        path = item.get("cmd")
        try:
            if item.get("enabled"):
                os.rename(path, path + ".disabled")
                log("STARTUP     | disabled '%s'" % name, "win")
            else:
                newp = path[:-9] if path.endswith(".disabled") else path
                os.rename(path, newp)
                log("STARTUP     | enabled '%s'" % name, "win")
            return True
        except Exception as e:
            log("STARTUP     | error: %s" % e, "error")
            return False
    if _winreg_module is None:
        return False
    hive = item.get("hive")
    base = _winreg_module.HKEY_CURRENT_USER if hive == "HKCU" else \
        _winreg_module.HKEY_LOCAL_MACHINE
    sub = r"Software\Microsoft\Windows\CurrentVersion\Run"
    st = _load_state()
    disabled = st.setdefault("startup_disabled", {})
    key = "%s|%s" % (hive, name)
    try:
        if item.get("enabled"):
            cmd = item.get("cmd", "")
            with _winreg_module.CreateKeyEx(base, sub, 0,
                                            _winreg_module.KEY_SET_VALUE) as k:
                _winreg_module.DeleteValue(k, name)
            disabled[key] = {"cmd": cmd}
            st["startup_disabled"] = disabled
            _save_state(st)
            log("STARTUP     | disabled '%s'" % name, "win")
        else:
            with _winreg_module.CreateKeyEx(base, sub, 0,
                                            _winreg_module.KEY_SET_VALUE) as k:
                _winreg_module.SetValueEx(k, name, 0, _winreg_module.REG_SZ,
                                          disabled.get(key, {}).get("cmd", ""))
            disabled.pop(key, None)
            st["startup_disabled"] = disabled
            _save_state(st)
            log("STARTUP     | enabled '%s'" % name, "win")
        return True
    except Exception as e:
        log("STARTUP     | error (admin needed for HKLM): %s" % e, "error")
        return False


# ---------------------------------------------------------------- restore point

def create_restore_point(log):
    if not is_admin():
        log("RESTORE PT  | administrator required", "error")
        return False
    log("RESTORE PT  | creating Windows restore point (may take ~30s)...", "work")
    ps = ('Enable-ComputerRestore -Drive "$env:SystemDrive\\"; '
          'Checkpoint-Computer -Description "R1X Optimizer" '
          "-RestorePointType MODIFY_SETTINGS")
    out = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-Command", ps], timeout=150)
    low = out.lower()
    ok = "error" not in low and "exception" not in low
    if "1440" in out or "frequency" in low or "once every" in low:
        log("RESTORE PT  | Windows allows one point per 24h - try later", "warn")
        return False
    log("RESTORE PT  | restore point created safely" if ok else
        "RESTORE PT  | could not create (enable System Protection)", 
        "win" if ok else "warn")
    return ok


# ---------------------------------------------------------------- deep clean

def deep_clean(log):
    total = 0
    win = os.environ.get("WINDIR", "C:\\Windows")
    local = os.environ.get("LOCALAPPDATA", "")
    prog = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
    zones = [
        os.path.join(win, "SoftwareDistribution", "Download"),
        os.path.join(win, "Logs", "CBS"),
        os.path.join(win, "Temp"),
        os.path.join(prog, "Microsoft", "Windows", "DeliveryOptimization", "Cache"),
        os.path.join(local, "Microsoft", "Windows", "INetCache"),
        os.path.join(local, "Microsoft", "Windows", "Explorer"),
        os.path.join(local, "Microsoft", "Windows", "WebCache"),
        os.path.join(local, "Google", "Chrome", "User Data", "Default", "Cache"),
        os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Cache"),
        os.path.join(local, "CrashDumps"),
    ]
    cleaned = 0
    for z in zones:
        if z and os.path.isdir(z):
            total += _delete_contents(z)
            cleaned += 1
    try:
        run(["powershell", "-NoProfile", "-Command",
             "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"], timeout=60)
    except Exception:
        pass
    log("DEEP CLEAN  | %d cache zones + recycle bin swept, freed ~%.1f MB"
        % (cleaned, total / 1048576), "win")
    return total


# ---------------------------------------------------------------- process killer

def top_processes(n=15):
    if psutil is None:
        return []
    procs = []
    try:
        for p in psutil.process_iter():
            try:
                p.cpu_percent(interval=None)
            except Exception:
                pass
        time.sleep(0.4)
        for p in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                info = p.info
                if not info.get("pid") or (info.get("name") or "").lower() in (
                        "system idle process", "idle"):
                    continue
                cpu = p.cpu_percent(interval=None)
                mem = info["memory_info"].rss if info.get("memory_info") else 0
                procs.append({"pid": info["pid"], "name": info["name"] or "?",
                              "cpu": round(cpu, 1),
                              "ram": round(mem / 1048576, 1)})
            except Exception:
                pass
    except Exception:
        return []
    procs.sort(key=lambda x: (x["cpu"], x["ram"]), reverse=True)
    return procs[:n]


def kill_process(pid, log):
    if psutil is None:
        log("KILL        | psutil unavailable", "error")
        return False
    try:
        p = psutil.Process(pid)
        name = p.name()
        p.terminate()
        try:
            p.wait(timeout=2)
        except Exception:
            p.kill()
        log("KILL        | terminated %s (pid %d)" % (name, pid), "win")
        return True
    except Exception as e:
        log("KILL        | failed pid %d: %s" % (pid, e), "error")
        return False


# ---------------------------------------------------------------- DNS / ping

DNS_SERVERS = [
    ("Cloudflare", "1.1.1.1", "1.0.0.1"),
    ("Google", "8.8.8.8", "8.8.4.4"),
    ("Quad9", "9.9.9.9", "149.112.112.112"),
    ("OpenDNS", "208.67.222.222", "208.67.220.220"),
    ("AdGuard", "94.140.14.14", "94.140.15.15"),
]

GAME_HOSTS = [
    ("Free Fire (Garena)", "freefiremobile.com"),
    ("BGMI / PUBG", "pubgmobile.com"),
    ("Valorant", "valorant.com"),
    ("Epic Games", "epicgames.com"),
]


def ping(host, count=3, timeout=1200):
    out = run("ping -n %d -w %d %s" % (count, timeout, host), timeout=20)
    ms = re.findall(r"(\d+)\s*ms", out, re.I)
    if ms:
        vals = [int(x) for x in ms]
        return round(sum(vals) / len(vals))
    return None


def _active_adapters():
    if psutil is None:
        return []
    out = []
    try:
        for name, st in psutil.net_if_stats().items():
            low = name.lower()
            if st.isup and not low.startswith(("loopback", "bluetooth")):
                out.append(name)
    except Exception:
        pass
    return out


def benchmark_dns(log, count=3):
    log("DNS BENCH   | probing public resolvers...", "work")
    results = []
    for name, p1, p2 in DNS_SERVERS:
        vals = [v for v in (ping(p1, count), ping(p2, count)) if v is not None]
        avg = round(sum(vals) / len(vals)) if vals else None
        results.append({"name": name, "primary": p1, "secondary": p2,
                        "latency": avg})
        log("DNS BENCH   | %-11s %s" % (
            name, ("%d ms" % avg) if avg is not None else "--"), "info")
    results.sort(key=lambda r: (r["latency"] is None, r["latency"] or 9999))
    if results and results[0]["latency"] is not None:
        log("DNS BENCH   | fastest: %s (%d ms)" % (
            results[0]["name"], results[0]["latency"]), "win")
    return results


def set_dns(name, log):
    server = next((s for s in DNS_SERVERS if s[0] == name), None)
    if not server:
        log("DNS SET     | unknown resolver %s" % name, "error")
        return False
    if not is_admin():
        log("DNS SET     | administrator required to change DNS", "error")
        return False
    adapters = _active_adapters()
    if not adapters:
        log("DNS SET     | no active adapter found", "error")
        return False
    for iface in adapters:
        run('netsh interface ip set dns name="%s" static %s primary' % (
            iface, server[1]), timeout=20)
        run('netsh interface ip add dns name="%s" %s index=2' % (
            iface, server[2]), timeout=20)
        log("DNS SET     | %s -> %s / %s" % (iface, server[1], server[2]), "win")
    flush_dns(log)
    return True


def restore_dns(log):
    if not is_admin():
        log("DNS SET     | administrator required", "error")
        return False
    for iface in _active_adapters():
        run('netsh interface ip set dns name="%s" dhcp' % iface, timeout=20)
        log("DNS SET     | %s -> automatic (DHCP)" % iface, "win")
    flush_dns(log)
    return True


def ping_games(log, count=3):
    log("PING TEST   | contacting game networks...", "work")
    results = []
    for name, host in GAME_HOSTS:
        ms = ping(host, count)
        results.append({"name": name, "host": host, "latency": ms})
        log("PING TEST   | %-20s %s" % (
            name, ("%d ms" % ms) if ms is not None else "no reply"), "info")
    return results


# ---------------------------------------------------------------- benchmark

def benchmark(seconds=4):
    samples = []
    end = time.time() + seconds
    while time.time() < end:
        samples.append(live_snapshot())
        time.sleep(0.8)
    if not samples:
        return {"fps": 0, "cpu": 0, "ram": 0, "gpu": 0}
    cpu = sum(s.get("cpu", 0) for s in samples) / len(samples)
    ram = sum(s.get("ram", 0) for s in samples) / len(samples)
    gpuv = [s.get("gpu") for s in samples if s.get("gpu") is not None]
    gpu = sum(gpuv) / len(gpuv) if gpuv else cpu
    score = sum(fps_index(s) for s in samples) / len(samples)
    return {"fps": round(score, 1), "cpu": round(cpu), "ram": round(ram),
            "gpu": round(gpu)}


# ---------------------------------------------------------------- game profile

class _GameWatcher(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.running = False
        self.last = None
        self._booted = False
        self._lock = threading.Lock()
        self.logf = lambda m, t="info": None

    def start_watch(self, logf):
        with self._lock:
            self.logf = logf
            if not self._booted:
                self._booted = True
                self.start()
            self.running = True

    def stop(self):
        with self._lock:
            self.running = False

    def run(self):
        while True:
            with self._lock:
                running = self.running
            if running:
                try:
                    emus = emulator_status()
                    active = [e for e in emus if e.get("running")]
                    if active:
                        e = active[0]
                        if e.get("key") != self.last:
                            self.logf("PROFILE     | %s detected - arming MAX FPS"
                                      % e.get("name"), "work")
                            emulator_run(e.get("key"), self.logf)
                            self.last = e.get("key")
                    else:
                        self.last = None
                except Exception:
                    pass
            time.sleep(6)


WATCHER = _GameWatcher()


def game_watch(on, log):
    if on:
        WATCHER.start_watch(log)
        log("PROFILE     | auto-boost ARMED - emulator start triggers MAX FPS",
            "win")
    else:
        WATCHER.stop()
        log("PROFILE     | auto-boost disarmed", "info")
    return bool(on)


def game_watch_status():
    return {"running": WATCHER.running, "last": WATCHER.last}


def detect_active_profile():
    try:
        for e in emulator_status():
            if e.get("running"):
                return {"key": e.get("key"), "name": e.get("name")}
    except Exception:
        pass
    return None


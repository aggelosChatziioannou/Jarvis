# Install-DesktopShortcut.ps1
#
# Creates / replaces a desktop shortcut named "Jarvis" that launches
# Start-Jarvis.vbs (silent launcher) and pins the same AppUserModelID
# that the running Python process registers with Windows. This way:
#
#   - Pinned taskbar icon groups with the running app (no double entries)
#   - Jump lists / "Pin to taskbar" attribute the shortcut to "Jarvis"
#     instead of to "wscript.exe"
#   - The icon is the Jarvis idle icon, not a generic Python logo
#
# Usage:  Right-click -> Run with PowerShell  (one-time)

$ErrorActionPreference = 'Stop'

$desktop      = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'Jarvis.lnk'
$vbsTarget    = 'C:\Users\aggel\Jarvis-src\Start-Jarvis.vbs'
$workingDir   = 'C:\Users\aggel\Jarvis-src'
$brandedIcon  = 'C:\Users\aggel\Jarvis-src\src\desktop_app\desktop_assets\icon_idle.ico'
$binaryIcon   = 'C:\Program Files\Jarvis\Jarvis.exe'
$appUserModelId = 'Jarvis.Desktop.Assistant'

if (-not (Test-Path $vbsTarget)) {
    Write-Host "ERROR: launcher not found at $vbsTarget" -ForegroundColor Red
    exit 1
}

# Icon priority: branded source-build .ico -> installed binary -> last resort pythonw
if (Test-Path $brandedIcon) {
    $iconPath = "$brandedIcon,0"
} elseif (Test-Path $binaryIcon) {
    $iconPath = "$binaryIcon,0"
} else {
    $iconPath = "C:\Users\aggel\Jarvis-src\.venv\Scripts\pythonw.exe,0"
}

Write-Host "Creating shortcut: $shortcutPath" -ForegroundColor Cyan
Write-Host "  Target  : wscript.exe `"$vbsTarget`"" -ForegroundColor DarkGray
Write-Host "  WorkDir : $workingDir" -ForegroundColor DarkGray
Write-Host "  Icon    : $iconPath" -ForegroundColor DarkGray
Write-Host "  AppID   : $appUserModelId" -ForegroundColor DarkGray

$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($shortcutPath)
# Use wscript.exe to host the .vbs - silent, no console window
$lnk.TargetPath       = "$env:WINDIR\System32\wscript.exe"
$lnk.Arguments        = "`"$vbsTarget`""
$lnk.WorkingDirectory = $workingDir
$lnk.IconLocation     = $iconPath
$lnk.Description      = 'Jarvis AI Assistant (source build with voice clone + fast-paths)'
$lnk.WindowStyle      = 7   # minimized (wscript itself never shows anyway)
$lnk.Save()

# Release the COM object so the file handle is freed before we re-open the
# .lnk to stamp its AppUserModelID property.
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($lnk) | Out-Null
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($wsh) | Out-Null

# --- AppUserModelID stamping ----------------------------------------------
# Without this, Windows derives an identity from the target binary
# (wscript.exe), so the pinned shortcut and the running Jarvis process end up
# in separate taskbar groups. Stamping the same ID the Python process
# registers via SetCurrentProcessExplicitAppUserModelID makes them collapse
# into one icon.

$setterSource = @'
using System;
using System.Runtime.InteropServices;

namespace JarvisShortcut2
{
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    public struct PropertyKey
    {
        public Guid FormatId;
        public uint PropertyId;
    }

    [StructLayout(LayoutKind.Explicit)]
    public struct PropVariant
    {
        [FieldOffset(0)] public ushort VarType;
        [FieldOffset(2)] public ushort wReserved1;
        [FieldOffset(4)] public ushort wReserved2;
        [FieldOffset(6)] public ushort wReserved3;
        [FieldOffset(8)] public IntPtr UnionPtr;
        [FieldOffset(16)] public int UnionAlignmentPadding;
    }

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IPropertyStore
    {
        uint GetCount();
        uint GetAt(uint iProp, out PropertyKey pkey);
        void GetValue(ref PropertyKey key, out PropVariant pv);
        void SetValue(ref PropertyKey key, ref PropVariant pv);
        void Commit();
    }

    public static class AumidSetter
    {
        [DllImport("shell32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, PreserveSig = false)]
        public static extern void SHGetPropertyStoreFromParsingName(
            [MarshalAs(UnmanagedType.LPWStr)] string pszPath,
            IntPtr zoneIdentifier,
            int flags,
            ref Guid riid,
            [Out, MarshalAs(UnmanagedType.Interface)] out IPropertyStore propertyStore);

        public static void Set(string lnkPath, string appId)
        {
            const int GPS_READWRITE = 0x2;
            Guid iid = typeof(IPropertyStore).GUID;
            IPropertyStore store;
            SHGetPropertyStoreFromParsingName(lnkPath, IntPtr.Zero, GPS_READWRITE, ref iid, out store);

            try
            {
                var key = new PropertyKey
                {
                    FormatId = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"),
                    PropertyId = 5
                };
                // Build VT_LPWSTR PropVariant manually — avoids InitPropVariantFromString
                // which is absent from the 32-bit propsys.dll on some Windows versions.
                var pv = new PropVariant();
                pv.VarType = 0x1F; // VT_LPWSTR
                pv.UnionPtr = Marshal.StringToCoTaskMemUni(appId);
                try
                {
                    store.SetValue(ref key, ref pv);
                    store.Commit();
                }
                finally
                {
                    if (pv.UnionPtr != IntPtr.Zero)
                        Marshal.FreeCoTaskMem(pv.UnionPtr);
                }
            }
            finally
            {
                Marshal.ReleaseComObject(store);
            }
        }
    }
}
'@

try {
    if (-not ('JarvisShortcut2.AumidSetter' -as [type])) {
        Add-Type -TypeDefinition $setterSource -Language CSharp -ErrorAction Stop
    }
    [JarvisShortcut2.AumidSetter]::Set($shortcutPath, $appUserModelId)
    Write-Host "AppUserModelID stamped onto shortcut." -ForegroundColor Green
} catch {
    Write-Host "WARNING: could not stamp AppUserModelID: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "         (the shortcut still works, but taskbar grouping with the running app may be inconsistent)" -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "Shortcut created. Double-click 'Jarvis' on your desktop to start." -ForegroundColor Green
Write-Host ""
Write-Host "Tip: pin it to taskbar by right-clicking the shortcut > 'Pin to taskbar'." -ForegroundColor Yellow

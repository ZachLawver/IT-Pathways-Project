# TRACE - Studio 5000 / RSLinx Classic Automation Prototype
# Consolidated after steps 259-285, 2026-10-12.
# Run in 32-bit Windows PowerShell 5.1 (SysWOW64), in an interactive Windows VM session.
# No PLC downloads, firmware updates, or writes are implemented.
# Upload is explicitly opt-in and requires an open Who Active dialog.
# This script does NOT yet save ACD files, export L5K, or perform comparisons.

param(
    [ValidateSet('Inspect','Select','Upload')]
    [string]$Action = 'Inspect',
    [string]$TargetIP = '192.168.1.1',
    [string]$ExpectedModel = '1769-L30ER',
    [string]$DriverName = '192_168_1, Ethernet'
)

$ErrorActionPreference = 'Stop'
if ([Environment]::Is64BitProcess) {
    throw 'Use 32-bit PowerShell: C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
}

# STEP 270: Native Win32 and cross-process TreeView access (32-bit layout).
if (-not ('TraceNative' -as [type])) {
Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
public struct TraceTVItem {
    public uint mask;
    public IntPtr hItem;
    public uint state;
    public uint stateMask;
    public IntPtr pszText;
    public int cchTextMax;
    public int iImage;
    public int iSelectedImage;
    public int cChildren;
    public IntPtr lParam;
}
public class TraceNative {
    public delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr param);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr param);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumWindowsProc callback, IntPtr param);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int maxCount);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr hwnd, StringBuilder text, int maxCount);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr hwnd);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern IntPtr VirtualAllocEx(IntPtr process, IntPtr address, UIntPtr size, uint allocation, uint protection);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool VirtualFreeEx(IntPtr process, IntPtr address, UIntPtr size, uint type);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool WriteProcessMemory(IntPtr process, IntPtr address, byte[] data, int size, out IntPtr written);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool ReadProcessMemory(IntPtr process, IntPtr address, byte[] data, int size, out IntPtr read);
    [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr handle);
}
'@
}
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

function Get-WindowText([IntPtr]$Hwnd) {
    $sb = New-Object System.Text.StringBuilder 512
    [void][TraceNative]::GetWindowText($Hwnd, $sb, $sb.Capacity)
    return $sb.ToString()
}
function Get-ChildWindowByClass([IntPtr]$Parent, [string]$Class) {
    $matches = New-Object System.Collections.ArrayList
    $cb = [TraceNative+EnumWindowsProc]{
        param([IntPtr]$h, [IntPtr]$unused)
        $sb = New-Object System.Text.StringBuilder 256
        [void][TraceNative]::GetClassName($h, $sb, $sb.Capacity)
        if ($sb.ToString() -eq $Class) { [void]$matches.Add($h) }
        return $true
    }
    [void][TraceNative]::EnumChildWindows($Parent, $cb, [IntPtr]::Zero)
    return @($matches)
}
function Get-TreeNext([IntPtr]$Tree, [IntPtr]$Node, [int]$Relation) {
    # TVM_GETNEXTITEM 0x110A; TVGN_ROOT=0, NEXT=1, CHILD=4.
    return [TraceNative]::SendMessage($Tree, 0x110A, [IntPtr]$Relation, $Node)
}
function Get-TreeNodeText([IntPtr]$Tree, [IntPtr]$Node, [uint32]$OwnerPID) {
    # STEP 267/270: 32-bit TVITEMW in target process, read via TVM_GETITEMW.
    $proc = [IntPtr]::Zero
    $remote = [IntPtr]::Zero
    $local = [IntPtr]::Zero
    try {
        $proc = [TraceNative]::OpenProcess(0x0038, $false, $OwnerPID)
        if ($proc -eq [IntPtr]::Zero) { throw "OpenProcess failed for PID $OwnerPID" }
        $remote = [TraceNative]::VirtualAllocEx($proc, [IntPtr]::Zero, [UIntPtr]::new([uint32]4096), 0x3000, 0x04)
        if ($remote -eq [IntPtr]::Zero) { throw 'VirtualAllocEx failed' }
        $item = [TraceTVItem]::new()
        $item.mask = 1
        $item.hItem = $Node
        $item.pszText = [IntPtr]::new($remote.ToInt32() + 1024)
        $item.cchTextMax = 256
        $size = [Runtime.InteropServices.Marshal]::SizeOf([type][TraceTVItem])
        $local = [Runtime.InteropServices.Marshal]::AllocHGlobal($size)
        [Runtime.InteropServices.Marshal]::StructureToPtr($item, $local, $false)
        $bytes = New-Object byte[] $size
        [Runtime.InteropServices.Marshal]::Copy($local, $bytes, 0, $size)
        $written = [IntPtr]::Zero
        if (-not [TraceNative]::WriteProcessMemory($proc, $remote, $bytes, $size, [ref]$written)) { throw 'WriteProcessMemory failed' }
        $ok = [TraceNative]::SendMessage($Tree, 0x113E, [IntPtr]::Zero, $remote) # TVM_GETITEMW
        if ($ok -eq [IntPtr]::Zero) { throw 'TVM_GETITEMW failed' }
        $textBytes = New-Object byte[] 512
        $read = [IntPtr]::Zero
        if (-not [TraceNative]::ReadProcessMemory($proc, $item.pszText, $textBytes, 512, [ref]$read)) { throw 'ReadProcessMemory failed' }
        return ([Text.Encoding]::Unicode.GetString($textBytes)).Split([char]0)[0]
    }
    finally {
        if ($local -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::FreeHGlobal($local) }
        if ($remote -ne [IntPtr]::Zero) { [void][TraceNative]::VirtualFreeEx($proc, $remote, [UIntPtr]::Zero, 0x8000) }
        if ($proc -ne [IntPtr]::Zero) { [void][TraceNative]::CloseHandle($proc) }
    }
}
function Get-DirectTreeChildren([IntPtr]$Tree, [IntPtr]$Parent, [uint32]$OwnerPID) {
    $node = Get-TreeNext $Tree $Parent 4
    $index = 0
    while ($node -ne [IntPtr]::Zero -and $index -lt 500) {
        [PSCustomObject]@{ Position = $index; Name = (Get-TreeNodeText $Tree $node $OwnerPID); Handle = $node }
        $node = Get-TreeNext $Tree $node 1
        $index++
    }
}

# STEP 271-273: Locate the RSLinx Classic RSWho tree and the exact target.
$rslinx = Get-Process | Where-Object { $_.MainWindowTitle -like 'RSLinx Classic Lite*' } | Select-Object -First 1
if (-not $rslinx) { throw 'Open RSLinx Classic RSWho first; its main window was not found.' }
$treeMatches = @(Get-ChildWindowByClass ([IntPtr]$rslinx.MainWindowHandle) 'SysTreeView32')
if ($treeMatches.Count -lt 1) { throw 'RSLinx SysTreeView32 not found.' }
$tree = [IntPtr]$treeMatches[0]
$root = Get-TreeNext $tree ([IntPtr]::Zero) 0
if ($root -eq [IntPtr]::Zero) { throw 'RSLinx tree root not found.' }
$drivers = @(Get-DirectTreeChildren $tree $root ([uint32]$rslinx.Id))
$driver = @($drivers | Where-Object { $_.Name -eq $DriverName })
if ($driver.Count -ne 1) { throw "Expected exactly one driver '$DriverName', found $($driver.Count)." }
$devices = @(Get-DirectTreeChildren $tree ([IntPtr]$driver[0].Handle) ([uint32]$rslinx.Id))
$ipPrefix = [regex]::Escape($TargetIP) + ','
$targets = @($devices | Where-Object { $_.Name -match "^$ipPrefix" -and $_.Name -like "*$ExpectedModel*" })
if ($targets.Count -ne 1) { throw "Expected exactly one $TargetIP / $ExpectedModel, found $($targets.Count)." }
$target = $targets[0]
Write-Host "RSLinx driver: $($driver[0].Name)"
Write-Host "Verified device: $($target.Name)"
Write-Host "Tree node: $($target.Handle)"

if ($Action -in @('Select','Upload')) {
    # STEP 273: TVM_SELECTITEM / TVGN_CARET.
    $selected = [TraceNative]::SendMessage($tree, 0x110B, [IntPtr]9, [IntPtr]$target.Handle)
    if ($selected -eq [IntPtr]::Zero) { throw 'RSLinx node selection failed.' }
    Write-Host 'RSLinx standalone RSWho selection: PASS'
}
if ($Action -eq 'Inspect') {
    Write-Host 'INSPECT COMPLETE: No selection or upload requested.'
    return
}
if ($Action -eq 'Select') {
    Write-Host 'SELECT COMPLETE: Studio Who Active has not been activated.'
    return
}

# STEP 280-284: Find the actual Who Active dialog dynamically (handles change).
# NOTE: Studio Who Active is distinct from the standalone RSLinx RSWho window.
$dialogs = New-Object System.Collections.ArrayList
$callback = [TraceNative+EnumWindowsProc]{
    param([IntPtr]$h, [IntPtr]$unused)
    if ((Get-WindowText $h) -eq 'Who Active (RSLinx Classic)') {
        [void]$dialogs.Add($h)
    }
    return $true
}
[void][TraceNative]::EnumWindows($callback, [IntPtr]::Zero)
if ($dialogs.Count -ne 1) {
    throw "Expected exactly one open Studio Who Active dialog; found $($dialogs.Count). Open Who Active in a clean Studio instance and retry."
}
$whoHwnd = [IntPtr]$dialogs[0]
$who = [System.Windows.Automation.AutomationElement]::FromHandle($whoHwnd)
$all = $who.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$expectedPath = ($DriverName -split ',')[0] + '\' + $TargetIP
$pathMatches = @($all | Where-Object { $_.Current.Name -eq $expectedPath })
if ($pathMatches.Count -ne 1) { throw "Studio Who Active selected path is not '$expectedPath'. Aborting." }
$uploadMatches = @($all | Where-Object { $_.Current.ClassName -eq 'Button' -and $_.Current.Name.Replace('&','') -eq 'Upload...' })
if ($uploadMatches.Count -ne 1) { throw 'Could not uniquely identify Upload button.' }
$button = [IntPtr]$uploadMatches[0].Current.NativeWindowHandle
if (-not [TraceNative]::IsWindow($button) -or -not [TraceNative]::IsWindowEnabled($button)) { throw 'Upload button unavailable.' }
if ((Get-WindowText $button).Replace('&','') -ne 'Upload...') { throw 'Upload button text mismatch.' }
Write-Host "Studio Who Active path: $expectedPath"
Write-Host "Verified Upload button: $button"
Write-Host 'Sending Upload button click (PLC -> PC)...'
# BM_CLICK can block while Studio displays a modal prompt. This was observed in Step 284A.
[void][TraceNative]::SendMessage($button, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)
Write-Host 'Upload click returned. Complete any subsequent Studio dialog manually.'

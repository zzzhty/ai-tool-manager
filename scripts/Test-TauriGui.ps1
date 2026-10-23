param([string]$Executable=(Join-Path $PSScriptRoot '../target/release/atm-desktop.exe'))
$ErrorActionPreference='Stop'
if(-not $IsWindows) { throw 'Windows GUI smoke requires Windows.' }
# Never start against the runner account's ordinary vault.
$root=Join-Path ([IO.Path]::GetTempPath()) ('lkm-tauri-smoke-'+[Guid]::NewGuid().ToString('N'))
$null=New-Item -ItemType Directory -Path $root
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class LkmWindow {
 [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
}
'@
$start=[Diagnostics.ProcessStartInfo]::new([IO.Path]::GetFullPath($Executable))
$start.UseShellExecute=$false
$start.ArgumentList.Add('--demo')
$start.Environment['LOCALAPPDATA']=$root
$start.Environment['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']='--force-renderer-accessibility'
$output=Join-Path $PSScriptRoot '../artifacts/tauri-gui'
$null=New-Item -ItemType Directory -Path $output -Force
$started=[DateTime]::UtcNow
$process=[Diagnostics.Process]::Start($start)
try {
  $deadline=[DateTime]::UtcNow.AddSeconds(45)
  $window=$null
  while([DateTime]::UtcNow -lt $deadline) {
    if($process.HasExited){throw 'Tauri exited before opening its synthetic test window.'}
    $condition=[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ProcessIdProperty,$process.Id)
    $window=[Windows.Automation.AutomationElement]::RootElement.FindFirst([Windows.Automation.TreeScope]::Children,$condition)
    if($window -and $window.Current.NativeWindowHandle -ne 0){break}
    Start-Sleep -Milliseconds 500
  }
  if(-not $window){throw 'Tauri window was not observable in this runner desktop.'}
  $handle=[IntPtr]$window.Current.NativeWindowHandle
  $null=[LkmWindow]::SetWindowPos($handle,[IntPtr]::Zero,40,40,620,460,0x0040)
  # A native window can exist before WebView2 publishes rendered accessibility controls.
  $renderDeadline=[DateTime]::UtcNow.AddSeconds(45)
  $names=@()
  do {
    if($process.HasExited){throw 'Tauri exited before rendering its synthetic test controls.'}
    $elements=$window.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition)
    $names=@(); foreach($element in $elements){try{$names+=$element.Current.Name}catch{}}
    if($names -match '密钥'){break}
    Start-Sleep -Milliseconds 500
  } while([DateTime]::UtcNow -lt $renderDeadline)
  $names|Set-Content -Encoding utf8 (Join-Path $output 'accessibility-names.txt')
  @{passed=$false;stage='rendered-controls';testedSha=(& git rev-parse HEAD);elapsedMilliseconds=([DateTime]::UtcNow-$started).TotalMilliseconds;controlCount=$names.Count}|ConvertTo-Json|Set-Content (Join-Path $output 'result.json')
  # Require rendered application text, not only a native empty WebView window.
  if(-not ($names -match '密钥')){throw 'No rendered application controls found through Windows accessibility.'}
  $bounds=$window.Current.BoundingRectangle
  if($bounds.Width -gt 660 -or $bounds.Height -gt 500){throw 'Small-window resize did not take effect.'}
  $bitmap=[Drawing.Bitmap]::new([int]$bounds.Width,[int]$bounds.Height)
  $graphics=[Drawing.Graphics]::FromImage($bitmap)
  try {
    $graphics.CopyFromScreen([int]$bounds.X,[int]$bounds.Y,0,0,$bitmap.Size)
    $bitmap.Save((Join-Path $output 'synthetic-small-window.png'))
  } finally {$graphics.Dispose();$bitmap.Dispose()}
  @{passed=$true;testedSha=(& git rev-parse HEAD);elapsedMilliseconds=([DateTime]::UtcNow-$started).TotalMilliseconds;scope='Synthetic isolated Windows startup, rendered accessibility controls and small-window resize only; frontend tests cover repeat/cancel flows.';width=$bounds.Width;height=$bounds.Height;controlCount=$names.Count}|ConvertTo-Json|Set-Content (Join-Path $output 'result.json')
  Write-Output 'TAURI_GUI_SMOKE=PASS (isolated fake-data startup/accessibility/small-window only)'
} finally {
  if(-not $process.HasExited){$null=$process.CloseMainWindow();if(-not $process.WaitForExit(5000)){$process.Kill()}}
  $process.Dispose()
  # Preserve failed-run test data for diagnosis; never touch ordinary user data.
}


param([ValidateSet('Staged','Head')][string]$Mode='Head')
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$allowed=@(Get-Content -LiteralPath (Join-Path $taskRoot 'scripts/source-manifest.json') -Raw | ConvertFrom-Json)
$tracked=@(& git -C $taskRoot -c core.quotepath=false ls-files)
if($LASTEXITCODE -ne 0 -or $tracked.Count -ne $allowed.Count -or (Compare-Object ($allowed|Sort-Object) ($tracked|Sort-Object))) { throw 'Tracked source manifest does not match the explicit project allowlist.' }
$decoder=[Text.UTF8Encoding]::new($false,$true)
$secretPattern='(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{24,}|-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----)'
foreach($relative in $allowed) {
  $reference=if($Mode -eq 'Staged'){':'+$relative}else{'HEAD:'+$relative}
  $info=[Diagnostics.ProcessStartInfo]::new()
  $info.FileName=(Get-Command git).Source
  $info.WorkingDirectory=$taskRoot
  $info.UseShellExecute=$false
  $info.RedirectStandardOutput=$true
  $info.RedirectStandardError=$true
  $info.ArgumentList.Add('cat-file');$info.ArgumentList.Add('blob');$info.ArgumentList.Add($reference)
  $process=[Diagnostics.Process]::Start($info)
  $errorTask=$process.StandardError.ReadToEndAsync()
  $memory=[IO.MemoryStream]::new()
  try {
    $process.StandardOutput.BaseStream.CopyTo($memory)
    if(-not $process.WaitForExit(20000)) {$process.Kill();throw 'Git source inspection timed out.'}
    if($process.ExitCode -ne 0){throw ('Cannot inspect Git blob: '+$relative)}
    $bytes=$memory.ToArray()
    try {$text=$decoder.GetString($bytes)} catch {throw ('Git contains non-UTF8 source: '+$relative)}
    if($text.StartsWith('%TSD-Header-###%') -or $text.Contains([char]0)) {throw ('Git contains opaque wrapped source: '+$relative)}
    if([regex]::IsMatch($text,$secretPattern)){throw ('Potential credential pattern in tracked source: '+$relative)}
    if([regex]::IsMatch($text,$secretPattern)){throw ('Potential credential pattern in tracked source: '+$relative)}
  } finally {$memory.Dispose();$process.Dispose()}
}
Write-Output ('SOURCE_AUDIT=PASS; '+$allowed.Count+' explicit Git blobs are readable UTF-8 project source; no runtime data, opaque wrappers or detected credential patterns.')
Write-Output 'This verifies Git content only; it does not prove absence of local transparent encryption.'

[CmdletBinding()]
param(
    [string]$Source = (Join-Path $PSScriptRoot '..\download\xi-gai.pptx'),
    [string]$OutDir = (Join-Path $PSScriptRoot '..\slides-export'),
    [int]$Width = 2560,
    [int]$Height = 1440
)

$ErrorActionPreference = 'Stop'

$sourcePath = (Resolve-Path -LiteralPath $Source).Path
$outPath = [System.IO.Path]::GetFullPath($OutDir)
New-Item -ItemType Directory -Force -Path $outPath | Out-Null
Get-ChildItem -LiteralPath $outPath -Filter 'slide-*.png' -ErrorAction SilentlyContinue |
    Remove-Item -Force

$powerPoint = $null
$presentation = $null
try {
    $powerPoint = New-Object -ComObject PowerPoint.Application
    $powerPoint.Visible = -1
    $presentation = $powerPoint.Presentations.Open($sourcePath, $true, $false, $false)

    $count = $presentation.Slides.Count
    for ($i = 1; $i -le $count; $i++) {
        $file = Join-Path $outPath ('slide-{0:D2}.png' -f $i)
        $presentation.Slides.Item($i).Export($file, 'PNG', $Width, $Height)
        Write-Output ("exported {0}/{1}" -f $i, $count)
    }
}
finally {
    if ($presentation) { $presentation.Close() }
    if ($powerPoint) { $powerPoint.Quit() }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

Write-Output ("done: {0}" -f $outPath)

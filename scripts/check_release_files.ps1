$ErrorActionPreference = "Stop"

$tracked = git ls-files
$forbiddenPatterns = @(
    '^\.venv/',
    '^node_modules/',
    '^_unused_current/',
    '^logs/',
    '^\.idea/',
    '^\.ollamassist/',
    '^__pycache__/',
    '^electron/dist/',
    '^db/user_templates/',
    '^db/search_templates\.json$',
    '^db/grid_templates\.json$',
    '^db/ui_state\.json$',
    '^db/safety_consent\.json$',
    '^db/center_anchor\.(json|png)$',
    '^chentr\.png$'
)

$badFiles = @()
foreach ($file in $tracked) {
    $normalized = $file -replace '\\', '/'
    foreach ($pattern in $forbiddenPatterns) {
        if ($normalized -match $pattern) {
            $badFiles += $file
            break
        }
    }
}

if ($badFiles.Count -gt 0) {
    Write-Error ("Forbidden release files are tracked:`n" + ($badFiles | Sort-Object -Unique | ForEach-Object { "  $_" }) -join "`n")
}

$textFiles = $tracked | Where-Object {
    $_ -match '\.(py|ts|js|json|md|txt|cmd|vbs|ps1|html|css)$'
}

$badText = @()
foreach ($file in $textFiles) {
    if (-not (Test-Path -LiteralPath $file)) {
        continue
    }
    $matches = Select-String -LiteralPath $file -Pattern 'C:\\dbd prokachka','C:\\\\dbd prokachka','YOUR_CHANNEL','YOUR_VK_ID','github.com/AurumWise/dbd-prokachka' -SimpleMatch -ErrorAction SilentlyContinue
    foreach ($match in $matches) {
        $badText += "{0}:{1}: {2}" -f $match.Path, $match.LineNumber, $match.Line.Trim()
    }
}

if ($badText.Count -gt 0) {
    Write-Error ("Release text checks failed:`n" + ($badText | Sort-Object -Unique | ForEach-Object { "  $_" }) -join "`n")
}

Write-Host "Release file check passed."

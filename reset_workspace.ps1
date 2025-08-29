# Reset workspace script - removes specified files and cleans KeepVault directory

# Remove individual files
if (Test-Path "keep_notes.json") {
    Remove-Item "keep_notes.json" -Force
    Write-Host "Removed keep_notes.json"
}

if (Test-Path "keep_state.json") {
    Remove-Item "keep_state.json" -Force
    Write-Host "Removed keep_state.json"
}

# Handle KeepVault directory - remove everything except Attachments folder
if (Test-Path "KeepVault") {
    $items = Get-ChildItem -Path "KeepVault" -Force
    
    foreach ($item in $items) {
        if ($item.Name -ne "Attachments") {
            Remove-Item -Path $item.FullName -Recurse -Force
            Write-Host "Removed KeepVault/$($item.Name)"
        }
    }
    
    Write-Host "Cleaned KeepVault directory (preserved Attachments folder)"
} else {
    Write-Host "KeepVault directory not found"
}

Write-Host "Workspace reset complete." 
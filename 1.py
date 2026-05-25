$imagePath = "C:\Users\PC\Downloads\wallet-qr-1777579278626.png"
$base64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($imagePath))
$body = @{
    messages = @(
        @{
            role = "user"
            content = @(
                @{ type = "text"; text = "Что на картинке?" }
                @{ type = "image_url"; image_url = @{ url = "data:image/jpeg;base64,$base64" } }
            )
        }
    )
    stream = $false
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "http://localhost:1234/v1/chat/completions" -Method Post -Body $body -ContentType "application/json"
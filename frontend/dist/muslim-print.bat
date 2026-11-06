@echo off
rem Программа печати кафе «Муслим»: принимает чеки от панели (окно Chrome на этом же компьютере)
rem и отправляет их на чековые аппараты по сети (IP, порт 9100). Окна не видно, работает в фоне.
rem Запуск: двойной щелчок. Для автозапуска положите этот файл в папку автозагрузки (Win+R -> shell:startup).
cd /d "%~dp0"
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "$t=[IO.File]::ReadAllText('%~nx0'); iex $t.Substring($t.IndexOf('#PS'+'-START'))"
exit /b
#PS-START
# ===== Дальше — PowerShell (подходит для Windows 7, PowerShell 2.0) =====
$Port = 18080                                                   # панель стучится на http://127.0.0.1:18080
$Allowed = @('https://muslim-cafe.com', 'http://localhost:4174', 'http://localhost:4175', 'http://127.0.0.1:4174')   # с каких сайтов принимать чеки
$Log = Join-Path $env:TEMP 'muslim-print.log'                   # журнал ошибок: %TEMP%\muslim-print.log

function Write-Log($text) {
    try { Add-Content -Path $Log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '  ' + $text) } catch { }
}

# Ответ панели (с разрешением для браузера — CORS)
function Send-Reply($stream, $code, $body, $origin) {
    $head = "HTTP/1.1 $code`r`nContent-Type: text/plain; charset=utf-8`r`nConnection: close`r`nCache-Control: no-store`r`n"
    if ($origin) {
        $head += "Access-Control-Allow-Origin: $origin`r`nAccess-Control-Allow-Methods: GET, POST, OPTIONS`r`n"
        $head += "Access-Control-Allow-Headers: Content-Type`r`nAccess-Control-Allow-Private-Network: true`r`nVary: Origin`r`n"
    }
    $data = [Text.Encoding]::UTF8.GetBytes($body)
    $head += "Content-Length: $($data.Length)`r`n`r`n"
    $bytes = [Text.Encoding]::ASCII.GetBytes($head)
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Write($data, 0, $data.Length)
    $stream.Flush()
}

# Отправить байты чека на аппарат (порт 9100). Аппарат не отвечает 3 секунды — ошибка
function Send-ToPrinter($ip, $bytes) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $wait = $client.BeginConnect($ip, 9100, $null, $null)
        if (-not $wait.AsyncWaitHandle.WaitOne(3000, $false)) { throw "аппарат $ip не отвечает" }
        $client.EndConnect($wait)
        $net = $client.GetStream()
        $net.Write($bytes, 0, $bytes.Length)
        $net.Flush()
        Start-Sleep -Milliseconds 300                           # дать аппарату принять всё до закрытия
    } finally { $client.Close() }
}

# Один запрос от панели
function Handle-Client($client) {
    $stream = $client.GetStream()
    $stream.ReadTimeout = 5000
    $buffer = New-Object byte[] 65536
    $received = New-Object System.IO.MemoryStream
    $headerEnd = -1
    while ($headerEnd -lt 0) {                                  # читаем заголовки
        $n = $stream.Read($buffer, 0, $buffer.Length)
        if ($n -le 0) { return }
        $received.Write($buffer, 0, $n)
        $text = [Text.Encoding]::ASCII.GetString($received.ToArray())
        $headerEnd = $text.IndexOf("`r`n`r`n")
        if ($received.Length -gt 1048576) { return }
    }
    $lines = $text.Substring(0, $headerEnd).Split("`n")
    $first = $lines[0].Trim().Split(' ')
    $method = $first[0]; $path = $first[1]
    $length = 0; $origin = ''
    foreach ($line in $lines) {
        if ($line -match '^Content-Length:\s*(\d+)') { $length = [int]$matches[1] }
        if ($line -match '^Origin:\s*(\S+)') { $origin = $matches[1].Trim() }
    }
    if ($origin -and ($Allowed -notcontains $origin)) { Send-Reply $stream '403 Forbidden' 'origin' ''; return }

    if ($method -eq 'OPTIONS') { Send-Reply $stream '204 No Content' '' $origin; return }
    if ($method -eq 'GET' -and $path -like '/ping*') { Send-Reply $stream '200 OK' 'muslim-print 1' $origin; return }
    $ip = ''
    if ($method -eq 'POST' -and $path -match '^/print\?ip=([0-9.]+)$') { $ip = $matches[1] }
    if (-not $ip) { Send-Reply $stream '404 Not Found' 'not found' $origin; return }
    if ($ip -notmatch '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)') { Send-Reply $stream '400 Bad Request' 'только адреса локальной сети' $origin; return }

    $bodyStart = $headerEnd + 4                                 # дочитываем тело (base64)
    while (($received.Length - $bodyStart) -lt $length) {
        $n = $stream.Read($buffer, 0, $buffer.Length)
        if ($n -le 0) { break }
        $received.Write($buffer, 0, $n)
    }
    $body = [Text.Encoding]::ASCII.GetString($received.ToArray(), $bodyStart, [Math]::Min($length, $received.Length - $bodyStart))
    try {
        $bytes = [Convert]::FromBase64String($body.Trim())
        Send-ToPrinter $ip $bytes
        Send-Reply $stream '200 OK' 'ok' $origin
    } catch {
        Write-Log "печать на $ip не удалась: $($_.Exception.Message)"
        Send-Reply $stream '502 Bad Gateway' ("" + $_.Exception.Message) $origin
    }
}

# Запуск: если программа уже работает (порт занят) — тихо выходим
try {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
    $listener.Start()
} catch { Write-Log "уже запущена или порт $Port занят"; exit }
Write-Log 'программа печати запущена'
while ($true) {
    $client = $listener.AcceptTcpClient()
    try { Handle-Client $client } catch { Write-Log "ошибка: $($_.Exception.Message)" } finally { $client.Close() }
}

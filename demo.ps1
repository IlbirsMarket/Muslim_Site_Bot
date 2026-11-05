# Демо-версия кафе «Муслим» — запускается ТОЛЬКО на этом компьютере.
# Своя база demo.sqlite3 и свои фото demo_media\ — настоящая база db.sqlite3 не трогается.
# Запуск: двойной щелчок по demo.bat. Новая демо-база с нуля: demo.bat new

param([string]$Mode = "")                                   # "new" — пересоздать демо-базу
$ErrorActionPreference = "Stop"                             # любая ошибка — сразу стоп
Set-Location $PSScriptRoot                                  # работаем из папки проекта
$py = Join-Path $PSScriptRoot "venv\Scripts\python.exe"     # Python из виртуального окружения
if (-not (Test-Path $py)) { Write-Host "Не найден venv\Scripts\python.exe — сначала создайте venv." -ForegroundColor Red; Read-Host "Enter — закрыть"; exit 1 }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Write-Host "Не найден Node.js — установите его с nodejs.org." -ForegroundColor Red; Read-Host "Enter — закрыть"; exit 1 }
$settings = "--settings=config.settings.demo"               # демо-настройки (своя база, без ботов)

if ($Mode -eq "new" -and (Test-Path "demo.sqlite3")) { Remove-Item "demo.sqlite3" }   # по просьбе — с чистого листа
if (-not (Test-Path "demo.sqlite3")) {                      # первый запуск — создаём и заполняем базу
    Write-Host "Создаю демо-базу..." -ForegroundColor Yellow
    & $py manage.py migrate $settings --noinput             # таблицы
    if ($LASTEXITCODE -ne 0) { Read-Host "Ошибка миграции. Enter — закрыть"; exit 1 }
    & $py manage.py createcachetable $settings              # таблица кэша (без неё не работает вход)
    Write-Host "Заполняю как настоящее кафе и скачиваю свободные фото (нужен интернет, 1–2 минуты)..." -ForegroundColor Yellow
    & $py manage.py seed_demo $settings                     # блюда, сотрудники, заказы, фото
    if ($LASTEXITCODE -ne 0) { Remove-Item "demo.sqlite3" -ErrorAction SilentlyContinue; Read-Host "Ошибка заполнения. Enter — закрыть"; exit 1 }
}

# Сервер демо-API на порту 8001 (настоящий проект обычно на 8000 — не мешают друг другу)
$api = Start-Process $py -ArgumentList "manage.py","runserver","127.0.0.1:8001",$settings,"--noreload" -PassThru -WindowStyle Minimized
# Сайт демо на порту 4175: MUSLIM_DEMO=1 включает демо-полосу и кнопки входа по ролям
$env:MUSLIM_DEMO = "1"; $env:MUSLIM_API_ORIGIN = "http://127.0.0.1:8001"; $env:PORT = "4175"
$web = Start-Process node -ArgumentList "frontend\server.cjs" -PassThru -WindowStyle Minimized
Start-Sleep -Seconds 3                                      # даём серверам запуститься
Start-Process "http://localhost:4175/admin"                 # открываем панель в браузере

Write-Host ""
Write-Host "Демо работает:" -ForegroundColor Green
Write-Host "  Панель персонала:  http://localhost:4175/admin   (вход кнопками ролей)"
Write-Host "  Меню гостя:        http://localhost:4175/"
Write-Host "  Авторы фото:       demo_media\АВТОРЫ-ФОТО.txt"
Write-Host ""
Read-Host "Нажмите Enter, чтобы остановить демо"
foreach ($p in @($api, $web)) { if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force } }   # гасим оба сервера

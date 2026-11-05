@echo off
rem Кухонный аппарат кафе «Муслим»: отдельное окно Chrome, которое печатает только кухонные чеки.
rem Положите ярлык этого файла на рабочий стол кассы и открывайте панель только через него.
rem В этом окне один раз выберите кухонный принтер в окне печати (см. инструкцию) — Chrome его запомнит.
chcp 65001 >nul
set CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe
if not exist "%CHROME%" set CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe
if not exist "%CHROME%" set CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe
if not exist "%CHROME%" (echo Не найден Google Chrome. Установите его с google.com/chrome & pause & exit /b 1)
rem Отдельный профиль: флаг тихой печати работает, даже если обычный Chrome уже открыт
start "" "%CHROME%" --kiosk-printing --user-data-dir="%LocalAppData%\MuslimKitchen" https://muslim-cafe.com/admin

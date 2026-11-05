@echo off
rem Кассовый компьютер кафе «Муслим»: панель в Chrome с тихой печатью чеков (без окна «Печать»).
rem Положите ярлык этого файла на рабочий стол кассы и открывайте панель только через него.
rem Чековый аппарат должен быть принтером «по умолчанию» в Windows.
chcp 65001 >nul
set CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe
if not exist "%CHROME%" set CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe
if not exist "%CHROME%" set CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe
if not exist "%CHROME%" (echo Не найден Google Chrome. Установите его с google.com/chrome & pause & exit /b 1)
rem Отдельный профиль: флаг тихой печати работает, даже если обычный Chrome уже открыт
start "" "%CHROME%" --kiosk-printing --user-data-dir="%LocalAppData%\MuslimKassa" https://muslim-cafe.com/admin

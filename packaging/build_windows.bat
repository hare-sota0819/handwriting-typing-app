@echo off
rem Build the distributable Windows app (double-click me on Windows).
rem Needs: Python 3.11+ from python.org, internet on first run (fetches
rem pinned pandoc + node portable binaries). Result: one app folder under
rem dist\ (name set in the spec; may be non-ASCII, so this .bat never
rem hardcodes it) — zip that folder and share it; recipients run the exe.

setlocal
cd /d "%~dp0.."

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python launcher not found. Install Python from python.org first.
  if not defined NO_PAUSE pause
  exit /b 1
)

if not exist .venv-win (
  py -3 -m venv .venv-win || (echo venv creation failed & if not defined NO_PAUSE pause & exit /b 1)
)
call .venv-win\Scripts\activate.bat
pip install -q -r requirements.txt || (echo pip install failed & if not defined NO_PAUSE pause & exit /b 1)

rem ---- fetch pinned tools once (official release artifacts)
set PANDOC_VER=3.5
set NODE_VER=v22.12.0

if not exist tools\pandoc\pandoc.exe (
  echo Fetching pandoc %PANDOC_VER%...
  mkdir tools\pandoc 2>nul
  curl -L -o tools\pandoc.zip https://github.com/jgm/pandoc/releases/download/%PANDOC_VER%/pandoc-%PANDOC_VER%-windows-x86_64.zip || (echo pandoc download failed & if not defined NO_PAUSE pause & exit /b 1)
  tar -xf tools\pandoc.zip -C tools\pandoc --strip-components=1
  del tools\pandoc.zip
)

if not exist tools\node\node.exe (
  echo Fetching node %NODE_VER%...
  mkdir tools\node 2>nul
  curl -L -o tools\node.zip https://nodejs.org/dist/%NODE_VER%/node-%NODE_VER%-win-x64.zip || (echo node download failed & if not defined NO_PAUSE pause & exit /b 1)
  tar -xf tools\node.zip -C tools\node --strip-components=1
  del tools\node.zip
)

rem Stale app folders from an older name would confuse the locate step below.
if exist dist rmdir /s /q dist

pyinstaller packaging\handwriting_gui.spec --noconfirm || (echo PyInstaller failed & if not defined NO_PAUSE pause & exit /b 1)

echo.
echo Build OK. Verifying the bundle...
set APPDIR=
for /d %%D in (dist\*) do set APPDIR=%%D
if not defined APPDIR (echo build produced no dist folder & if not defined NO_PAUSE pause & exit /b 1)
set APPEXE=
for %%F in ("%APPDIR%\*.exe") do set APPEXE=%%F
"%APPEXE%" --selfcheck
if errorlevel 1 (
  echo SELFCHECK FAILED - details:
  type "%APPDIR%\selfcheck.log"
  if not defined NO_PAUSE pause
  exit /b 1
)
type "%APPDIR%\selfcheck.log"

echo.
echo DONE: %APPDIR%\  (zip this folder to distribute)
if not defined NO_PAUSE pause

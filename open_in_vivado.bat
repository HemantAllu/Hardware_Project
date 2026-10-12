@echo off
rem ---------------------------------------------------------------------------
rem  open_in_vivado.bat : double-click to build the project from .\src and open it in Vivado.
rem  Looks for Vivado on PATH and in the usual install folders (C:\Xilinx, C:\AMD, D:, E:).
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

if not exist "src\rtl\soc_top.v" (
  echo.
  echo ERROR: src\rtl\soc_top.v was not found next to this file.
  echo You are probably running this from INSIDE the zip. Close it, right-click the zip,
  echo choose "Extract All...", and run this file from the extracted folder.
  echo.
  pause
  exit /b 1
)

set "VIVADO_CMD="
where vivado >nul 2>nul
if not errorlevel 1 set "VIVADO_CMD=vivado"

if not defined VIVADO_CMD (
  for %%R in (C D E) do (
    for /d %%D in ("%%R:\Xilinx\Vivado\*") do if exist "%%~D\bin\vivado.bat" set "VIVADO_CMD=%%~D\bin\vivado.bat"
    for /d %%D in ("%%R:\AMD\Vivado\*")    do if exist "%%~D\bin\vivado.bat" set "VIVADO_CMD=%%~D\bin\vivado.bat"
    for /d %%D in ("%%R:\AMD\*")           do if exist "%%~D\Vivado\bin\vivado.bat" set "VIVADO_CMD=%%~D\Vivado\bin\vivado.bat"
  )
)

if not defined VIVADO_CMD (
  echo.
  echo Could not find Vivado automatically.
  echo Open Vivado yourself, then:  Tools - Run Tcl Script...  and pick create_project.tcl
  echo in this folder.
  echo.
  pause
  exit /b 1
)

echo Using: %VIVADO_CMD%
call "%VIVADO_CMD%" -mode gui -log "%~dp0vivado_launch.log" -journal "%~dp0vivado_launch.jou" -source "%~dp0create_project.tcl"
endlocal

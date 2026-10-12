@echo off
rem ---------------------------------------------------------------------------
rem  run_sim.bat : runs the MUL/DIV testbench with the Vivado simulator WITHOUT the GUI.
rem  Use it if "Run Behavioral Simulation" fails inside Vivado. Double-click it.
rem  It only uses short relative paths, so spaces or brackets in folder names do not matter.
rem  Expected last lines:  tb_muldiv: 25152 checks, 0 errors   and   TB_MULDIV PASS
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "VBIN="
where xvlog >nul 2>nul
if not errorlevel 1 goto have_path

for %%R in (C D E) do (
  for /d %%D in ("%%R:\Xilinx\Vivado\*") do if exist "%%~D\bin\xvlog.bat" set "VBIN=%%~D\bin\"
  for /d %%D in ("%%R:\AMD\Vivado\*")    do if exist "%%~D\bin\xvlog.bat" set "VBIN=%%~D\bin\"
  for /d %%D in ("%%R:\AMD\*")           do if exist "%%~D\Vivado\bin\xvlog.bat" set "VBIN=%%~D\Vivado\bin\"
  for /d %%D in ("%%R:\AMDDesignTools\*") do if exist "%%~D\Vivado\bin\xvlog.bat" set "VBIN=%%~D\Vivado\bin\"
)
if not defined VBIN goto no_vivado

:have_path
if not exist sim_out mkdir sim_out
cd sim_out
echo === compiling ===
call "%VBIN%xvlog" ..\src\sim\tb_muldiv.v ..\src\rtl\muldiv_unit.v
if errorlevel 1 goto failed
echo === elaborating ===
call "%VBIN%xelab" tb_muldiv -s tb_muldiv_sim -debug off
if errorlevel 1 goto failed
echo === simulating ===
call "%VBIN%xsim" tb_muldiv_sim -R
cd ..
echo.
echo Done. Logs are in the sim_out folder.
pause
exit /b 0

:no_vivado
echo Could not find Vivado. Open "Vivado 2025.2 Tcl Shell" from the Start menu,
echo cd to this folder, and run:  run_sim.bat
pause
exit /b 1

:failed
cd ..
echo.
echo FAILED - send a screenshot of this window and the files in the sim_out folder.
pause
exit /b 1

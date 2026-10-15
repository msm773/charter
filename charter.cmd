@echo off
rem Charter launcher for Windows: run charter once this folder is on
rem PATH. Paths are read from where you run it; standard input, output and the
rem exit status pass straight through.
rem
rem It runs the first real Python 3.9 or later it finds: the Windows launcher
rem `py -3`, then `python`. Each is proved by running it, so an older Python, or
rem the Microsoft Store's `python` stand-in when no Python is installed, is
rem passed over rather than run.
setlocal
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" <nul >nul 2>nul
if not errorlevel 1 goto run_py
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" <nul >nul 2>nul
if not errorlevel 1 goto run_python
>&2 echo charter: Python 3.9 or later was not found. Install it from python.org, with the py launcher.
exit /b 9009
:run_py
py -3 "%~dp0charter.py" %*
exit /b %errorlevel%
:run_python
python "%~dp0charter.py" %*
exit /b %errorlevel%

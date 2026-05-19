@echo off
REM mfi — Medicaid Inspector command-line wrapper (Windows).
REM Calls the CLI as a module so relative imports inside backend/ resolve.
python -m backend.cli.mfi %*

@echo off
:: Create .env from .env.example if it doesn't exist so Docker's --env-file doesn't fail

if not exist .env (
    copy .env.example .env >nul
)

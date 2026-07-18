#!/bin/bash
# Doble clic en este archivo para instalar (la primera vez) y arrancar el bot.
set -e
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "Primera vez: creando entorno e instalando dependencias..."
    python3 -m venv venv
    ./venv/bin/pip install --quiet --upgrade pip
    ./venv/bin/pip install --quiet -r requirements.txt
fi

if [ ! -f ".env" ]; then
    cp .env.example .env
fi

./venv/bin/python main.py --web

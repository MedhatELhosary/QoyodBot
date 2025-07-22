#!/bin/bash

# تثبيت wkhtmltopdf
apt-get update
apt-get install -y ./bin/wkhtmltox_0.12.6-1.focal_amd64.deb

# بدء البوت
python telegram_bot.py

#!/bin/bash

apt-get update && apt-get install -y netcat-openbsd

until nc -z -v -w30 loggino_db 5432
do
  echo "Waiting for database connection..."
  sleep 5
done

echo "Database is up. Starting Loggino..."
python3 loggino.py

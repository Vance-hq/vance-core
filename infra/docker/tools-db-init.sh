#!/bin/bash
# Creates one database per tool that needs its own Postgres DB.
# Runs automatically on first docker compose up via initdb.d mount.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE umami;
    CREATE DATABASE outline;
    CREATE DATABASE unleash;
    CREATE DATABASE twenty;
EOSQL

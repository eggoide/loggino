
# Loggino: Lightweight AI Log Analysis and Recommendation System

**Loggino** is a lightweight, containerized tool designed to **analyze error logs using OpenAI's GPT model** and provide **automated recommendations** on how to resolve them. The results are displayed in a simple web interface.

---

![Loggino UI Screenshot](loggino.jpg)

---

## What Makes Loggino Special?

Unlike traditional log collectors, **Loggino integrates with OpenAI** to:
- Automatically send selected error and exception logs to the GPT model.
- Analyze them in natural language.
- Provide human-readable recommendations to resolve the issues.

---

## Project Structure

```
LOGGINO/
├── api_config.json           # OpenAI API configuration
├── docker-compose.yml        # Docker Compose configuration
├── Dockerfile                # Docker image for the Loggino app
├── entrypoint.sh             # Container startup script
├── fluent-bit.conf           # Fluent Bit configuration for log collection
├── loggino.py                # Main Loggino app logic
├── loggino_config.json       # App configuration
├── parsers.conf              # Log parsers for Fluent Bit
├── requirements.txt          # Python dependencies
├── static/
│   └── favicon.ico           # Web UI icon
└── templates/
    └── index.html            # Web interface HTML template
```

---

## How to Start

### 1. Requirements
- Docker
- Docker Compose

### 2. Configure Fluent Bit to your specific needs

### 3. Installation

```bash
cd DOCKER
docker-compose up --build
```

### 4. Access the Web UI
Open [http://localhost:5001](http://localhost:5001) in your browser.

---

## Configuration File Overview

### `api_config.json`

OpenAI API configuration:

```json
{
  "api_key": "...",
  "model": "gpt-3.5-turbo-0125"
}
```

- `api_key` - replace `...` with your actual API key.
- Be sure to **keep this file private**.
- `model` - choose relevant OpenAI model for your purpose.

---

### `docker-compose.yml`

Launches all required containers:

```yaml
services:
  loggino_db:
    image: postgres:13
    environment:
      POSTGRES_PASSWORD: secret
      POSTGRES_DB: loggino
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  fluent-bit:
    image: fluent/fluent-bit:2.0
    volumes:
      - ./fluent-bit.conf:/fluent-bit/etc/fluent-bit.conf
      - ./parsers.conf:/fluent-bit/etc/parsers.conf
      - ./evm.log:/var/log/miq_log/evm.log
    depends_on:
      - loggino_db

  loggino:
    build: .
    ports:
      - "5001:5001"
    volumes:
      - .:/app
    depends_on:
      - loggino_db

volumes:
  pgdata:
```

- `fluent-bit:volumes` - specify volume, that will be mounted to the container with logs to parse.
- `loggino:ports` - port that will be use for the web frontend. Needs to be same as defined in **loggino_config.json**.

---

### `Dockerfile`

Builds the Loggino image:

```Dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r requirements.txt
RUN chmod +x entrypoint.sh
CMD ["./entrypoint.sh"]
```

---


### `entrypoint.sh`

```bash
#!/bin/bash
echo "Starting Loggino Flask App..."
python loggino.py
```

Starts the Flask application.

---

### `fluent-bit.conf`

Controls how Fluent Bit collects and processes logs.

```ini
[INPUT]
    Name              tail
    Path              /var/log/miq_log/evm.log
    Tag               log.evm
    DB                /fluent-bit/db/fluent-bit-tail.db
    DB.Sync           normal
    DB.Locking        true
    Read_from_head    false
    Refresh_Interval  1
    Buffer_Max_Size   1M
    Skip_Long_Lines   off
    Path_Key          filename
    Parser_Firstline  stacktrace_parser
```
- Replace `Path` with your actual log file location.
- `Tag` is important for multiple log parsing. It needs to correspondent with relevant filters.

```ini
[FILTER]
    Name         grep
    Match        log.evm
    Regex        log ("level":"err"|"level":"crit"|critical|CRITICAL|error|ERROR|exception|EXCEPTION|FAILURE|failure)
```
- Only forwards important log levels (errors, exceptions). You can define various keywords/errors in `Regex`.

```ini
[FILTER]
    Name   modify
    Match  log.evm
    Add    description "Manage IQ server evm log"
    Add    resource "https://github.com/ManageIQ"
```
- Adds metadata to the log. These metadata are relevant for the AI inspection. `description` tells AI what system is being monitored. `resource` will be used to tell AI where to look for further information about the monitored system.

```ini
[OUTPUT]
    Name    pgsql
    Match   *
    Host    loggino_db
    Port    5432
    Database loggino
    User    postgres
    Password secret
    Table   logs
    Format  json
```
- Sends the log output into a PostgreSQL database.

---

### `loggino.py`

Main logic of the application:
- Reads logs from the database
- Cleans them
- Sends them to OpenAI
- Displays analysis in the web UI

---

### `loggino_config.json`

Application configuration for the Flask app:

```json
{
  "database_url": "postgresql://postgres:secret@loggino_db:5432/loggino",
  "log_limit": 20,
  "fluent_bit_config_path": "/app/fluent-bit.conf",
  "flask_port": 5001,
  "flask_host": "0.0.0.0",
  "app_version": "1.0.2",
    "timestamp_cleaning_patterns": [
        "^[A-Za-z]{3} \\d{1,2} \\d{2}:\\d{2}:\\d{2}",
        "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?Z?",
        "^\\d{4}/\\d{2}/\\d{2} \\d{2}:\\d{2}:\\d{2}",
        "\\b[a-zA-Z0-9_-]+\\[\\d+\\]:",
        "\\b[a-f0-9]{12,}\\b",
        "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?[+-]\\d{2}:\\d{2}"
    ]
}
```

- `log_limit`: Number of logs shown in the UI.
- `timestamp_cleaning_patterns`: Regex to clean timestamps before sending logs to GPT.
- `flask_port`: frontend application port


---

### `parsers.conf`

Defines multiline and custom parsers:

```ini
[MULTILINE_PARSER]
    Name          stacktrace_parser
    Type          regex
    Flush_MS      2000
    Rule          "start_state" "^.*(ERROR|error|EXCEPTION|exception|FAILURE|failure).*$"  "cont_state"
    Rule          "cont_state"  "^(?!.*(ERROR|error|EXCEPTION|exception|FAILURE|failure)).*$" "cont_state"
```

- This is how the logs, caught by fluent-bit, be parsed and saved to the DB.

---


## How to run the application

1. Restart the stack using:

```bash
docker-compose down
docker-compose up --build
```

2. Visit [http://localhost:5001](http://localhost:5001)

---

## Web Interface

- Lists recent error logs
- Shows AI-generated explanations and fix suggestions
- Simple and readable

---

## Contributions

This project is aimed at DevOps, SREs, and developers looking for AI-assisted log diagnostics.

---

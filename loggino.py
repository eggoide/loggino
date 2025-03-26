import time
from flask import Flask, request, render_template, jsonify
import psycopg2
import json
import openai
import re

app = Flask(__name__)

def load_config():
    """Reads configuration from file loggino_config.json"""
    try:
        with open("loggino_config.json", "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"ERROR reading the configuration: {e}")
        return {}

config = load_config()
DATABASE_URL = config.get("database_url", "postgresql://postgres:secret@127.0.0.1:5432/loggino")
LOG_LIMIT = config.get("log_limit", 20)
FLUENT_BIT_CONFIG_PATH = config.get("fluent_bit_config_path", "fluent-bit.conf")
FLASK_PORT = config.get("flask_port", 5001)
FLASK_HOST = config.get("flask_host", "0.0.0.0")
VERSION = config.get("app_version", "1.0.0")

def get_db_connection():
    """Establishing DB connection"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        print("Successfully connected to PostgreSQL")
        return conn
    except Exception as e:
        print(f"Database connection failed: {str(e)}")
        return None

def ensure_db_schema():
    """Checks for the necessary columns in the table and creates them if needed."""
    conn = get_db_connection()
    if not conn:
        print("Unable to connect to the database.")
        return
    
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name='logs' AND column_name='ai_response'
        """)
        if not cur.fetchone():
            print("Column 'ai_response' does not exist, creating it...")
            cur.execute("ALTER TABLE logs ADD COLUMN ai_response TEXT DEFAULT NULL;")
            conn.commit()
            print("Column 'ai_response' created.")

        cur.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name='logs' AND column_name='id'
        """)
        if not cur.fetchone():
            print("Column 'id' does not exist, creating it...")
            cur.execute("ALTER TABLE logs ADD COLUMN id SERIAL PRIMARY KEY;")
            conn.commit()
            print("Column 'id' created.")

        cur.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name='logs' AND column_name='unique_error'
        """)
        if not cur.fetchone():
            print("Column 'unique_error' does not exist, creating it...")
            cur.execute("ALTER TABLE logs ADD COLUMN unique_error  TEXT DEFAULT NULL;")
            conn.commit()
            print("Column 'unique_error' created.")            

        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB schema check error: {str(e)}")

def load_api_settings():
    """Load OpenAI API key and model."""
    try:
        with open("api_config.json", 'r') as f:
            config = json.load(f)
            return config.get("api_key"), config.get("model", "gpt-4")
    except Exception as e:
        print(f"Error - unable to load OpenAI API key: {e}")
        return None, "gpt-4"

def clean_log_line(log_line):
    """Cleans the log line using regex patterns from configuration."""
    patterns = config.get("timestamp_cleaning_patterns", [])
    for pattern in patterns:
        log_line = re.sub(pattern, '', log_line)
    return log_line.strip()

def analyze_error_with_chatgpt(error_message, description, resource):
    """Send the error to OpenAI and get a recommendation."""
    api_key, model = load_api_settings()
    if not api_key:
        return "OpenAI API key is missing."

    try:
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are an AI expert in log analysis. Help analyze errors."},
                {"role": "user", "content": f"This is a log error: {error_message} from system {description}. How can it be fixed? If necessary use this resource: {resource}"}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"OpenAI request failed: {str(e)}"

def analyze_and_store(log_entry):
    """Sends error for analysis to the AI and saves it to the DB"""
    conn = get_db_connection()
    if not conn:
        return "Database connection error"

    try:
        cur = conn.cursor()
        
        # Checks if there is a unique error in the DB
        cur.execute("SELECT ai_response FROM logs WHERE unique_error = %s AND ai_response IS NOT NULL LIMIT 1", 
                    (log_entry["unique_error"],))
        existing_ai_response = cur.fetchone()

        if existing_ai_response:
            ai_response = existing_ai_response[0]  # Use the existing AI response
        else:
            # If it does not exist, call the AI
            #ai_response = analyze_error_with_chatgpt(log_entry["error"], log_entry["description"], log_entry["resource"])
            ai_response = "Mocked AI response"

            # Saves the new response for a future use
            cur.execute("UPDATE logs SET ai_response = %s WHERE id = %s", (ai_response, log_entry["id"]))
            conn.commit()

        cur.close()
        conn.close()
        return ai_response

    except Exception as e:
        print(f"Error saving AI response: {e}")
        return "AI response storage error"

def save_unique_error(log_entry):
    unique_error = clean_log_line(log_entry["error"])
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("UPDATE logs SET unique_error = %s WHERE id = %s", (unique_error, log_entry["id"]))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Error saving unique_error: {e}")

@app.route("/")
def index():
    """Render of the HTML page."""
    return render_template("index.html")

@app.route("/get_logs")
def get_logs_from_db():
    """Returns X last logs and analyzes them"""
    conn = get_db_connection()
    if not conn:
        return jsonify([])

    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT id, tag, time, data::text, ai_response, unique_error FROM logs 
            ORDER BY id DESC
        """)
        records = cur.fetchall()
        cur.close()

        logs = []
        seen_errors = set()

        for row in records:
            log_data = json.loads(row[3])
            unique_error = clean_log_line(log_data.get("log", "No message"))

            # If this error has been already seen, skip it
            if unique_error in seen_errors:
                continue

            seen_errors.add(unique_error)

            log_entry = {
                "id": row[0],
                "tag": row[1],
                "timestamp": row[2].isoformat(),
                "error": log_data.get("log", "No message"),
                "filename": log_data.get("filename", "Unknown File"),
                "description": log_data.get("description", "No description"),
                "resource": log_data.get("resource", "No resource"),
                "ai_response": row[4],
                "unique_error": unique_error
            }

            save_unique_error(log_entry)

            # If the error has not been analzyed yet, analyze it and save the result
            if not row[4]:
                log_entry["ai_response"] = analyze_and_store(log_entry)

            logs.append(log_entry)

            # Limits the number of logs in the frontend -  LOG_LIMIT
            if len(logs) >= LOG_LIMIT:
                break

        conn.close()
        return jsonify(logs)

    except Exception as e:
        print(f"Error fetching logs from DB: {str(e)}")
        return jsonify([])

@app.route("/about")
def show_about():
    return f"App version: {VERSION}"

@app.route("/config")
def get_config():
    """Load Fluent Bit configuration"""
    try:
        with open(FLUENT_BIT_CONFIG_PATH, "r") as f:
            return f.read(), 200, {'Content-Type': 'text/plain'}
    except Exception as e:
        print(f"Error reading Fluent Bit config: {str(e)}")
        return f"Error reading config: {str(e)}", 500

if __name__ == "__main__":
    ensure_db_schema() 
    print(f"Starting Flask app on {FLASK_HOST}:{FLASK_PORT}...")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=True)

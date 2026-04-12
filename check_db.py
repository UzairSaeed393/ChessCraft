import psycopg2
import os
import environ

# Initialize environ
env = environ.Env()
# Read .env file
environ.Env.read_env('.env')

try:
    print(f"Attempting to connect to {env('DB_HOST')}...")
    conn = psycopg2.connect(
        dbname=env('DB_NAME'),
        user=env('DB_USER'),
        password=env('DB_PASSWORD'),
        host=env('DB_HOST'),
        port=env('DB_PORT'),
        connect_timeout=10
    )
    print("SUCCESS: Connection established!")
    conn.close()
except Exception as e:
    print(f"FAILED: {e}")

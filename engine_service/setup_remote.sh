#!/bin/bash

# Configuration - Change these if needed
DB_NAME="chesscraft_DB2"
DB_USER="chessuser"
DB_PASS="Charizard;1740"
ENGINE_TOKEN="UzairChessCraftToken1740"

echo "=== Starting Azure Setup for ChessCraft ==="

# 1. Update and Install Dependencies
sudo apt update
sudo apt install -y stockfish python3-pip python3-venv postgresql postgresql-contrib git

# 2. Database Setup
echo "=== Configuring PostgreSQL ==="
sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;"
sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"

# Allow Remote Connections for PostgreSQL
echo "listen_addresses = '*'" | sudo tee -a /etc/postgresql/*/main/postgresql.conf
echo "host all all 0.0.0.0/0 md5" | sudo tee -a /etc/postgresql/*/main/pg_hba.conf
sudo systemctl restart postgresql

# 3. Engine Service Setup
echo "=== Setting up Engine API ==="
mkdir -p ~/engine_service
# (Note: In a real flow, the user would upload the local files, 
# but for this script we assume they exist or we create a placeholder)

cd ~/engine_service
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn python-chess

# Create systemd service for the Engine API
sudo bash -c "cat > /etc/systemd/system/chess_engine.service <<EOF
[Unit]
Description=ChessCraft Stockfish API
After=network.target

[Service]
User=$USER
WorkingDirectory=$HOME/engine_service
ExecStart=$HOME/engine_service/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
Restart=always
Environment=ENGINE_TOKEN=$ENGINE_TOKEN

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload
sudo systemctl enable chess_engine
sudo systemctl start chess_engine

echo "=== Setup Complete! ==="
echo "PostgreSQL: port 5432, User: $DB_USER, DB: $DB_NAME"
echo "Engine API: port 8000, Token: $ENGINE_TOKEN"
echo "IMPORTANT: Update your local .env file with the Azure IP and these credentials."

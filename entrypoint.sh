#!/bin/bash
set -e

# Run database migrations/initialization if needed (using the init_db function)
# Ensure the database file exists or is created in the correct location
# We'll run a python command to call init_db from database.py
echo "Initializing database (if needed)..."
python -c "from database import init_db; init_db()"
echo "Database initialization complete."

# Start FastAPI backend in the background
echo "Starting FastAPI backend..."
uvicorn main:app --host 0.0.0.0 --port 8000 &

# Start Streamlit frontend in the foreground
echo "Starting Streamlit frontend..."
streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0

# Keep the script running (Streamlit handles this in the foreground)
exec "$@" 
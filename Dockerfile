# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies that might be needed by some python packages
# (e.g., build-essential for packages that compile C code)
# Add git for GitPython dependency
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Use --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container at /app
# Ensure .gitignore patterns are respected by using .dockerignore if needed
COPY . .

# Make the entrypoint script executable (redundant if already done, but safe)
RUN chmod +x /app/entrypoint.sh

# Expose FastAPI port
EXPOSE 8000
# Expose Streamlit port
EXPOSE 8501

# Define environment variables (optional, can be set at runtime)
# ENV OPENAI_API_KEY="your_key_here" # Example: Better to pass this at runtime
# ENV DATABASE_URL="sqlite:///data/proposals.db" # Example: Set DB path

# Specify the command to run on container start
ENTRYPOINT ["/app/entrypoint.sh"]

# Default command (can be overridden)
CMD [] 
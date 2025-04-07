#!/bin/bash

# Create virtual environment
python -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file from example
cp .env.example .env
echo "Please update the .env file with your configuration"

# Run the application
echo "Setup complete. Run the application with: python app.py"


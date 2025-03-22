FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies for FluidSynth
RUN apt-get update && apt-get install -y \
    build-essential \
    fluidsynth \
    libfluidsynth-dev \
    libjack-dev \
    libasound2-dev \
    libsndfile1-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Setup volume for datasets and cache
VOLUME /app/datasets
VOLUME /app/cache

# Create soundfont directory and copy soundfont
RUN mkdir -p /app/soundfonts

# Download FluidR3_GM.sf2 if it doesn't exist
RUN if [ ! -f /app/soundfonts/FluidR3_GM.sf2 ]; then \
    apt-get update && apt-get install -y wget && \
    wget -O /app/soundfonts/FluidR3_GM.sf2 https://www.dropbox.com/s/4z8sti7a1vu2snv/FluidR3_GM.sf2?dl=1 && \
    apt-get remove -y wget && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*; \
    fi

# Expose port
EXPOSE 5000

# Set environment variables
ENV FLASK_APP=web/app.py
ENV PYTHONPATH=/app

# Run application
CMD ["flask", "run", "--host=0.0.0.0"] 
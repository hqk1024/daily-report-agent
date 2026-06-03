FROM python:3.9-slim

WORKDIR /app

# Install root requirements
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install agent requirements (separate subdir)
COPY agent/requirements.txt ./agent/requirements.txt
RUN pip install --no-cache-dir -r agent/requirements.txt

# Copy application code and install as package
COPY servers/ servers/
COPY agent/ agent/
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["python", "agent/agent.py", "--api", "--host", "0.0.0.0", "--port", "8000"]

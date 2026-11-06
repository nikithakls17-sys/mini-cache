# Dockerfile - packages the server so it runs the same anywhere
# (your laptop, or an OCI Always Free VM).

# Start from a small official Python image
FROM python:3.12-slim

# Work inside /app in the container
WORKDIR /app

# Copy the code in (no extra libraries needed: only Python's standard library)
COPY cache.py server.py ./

# Document the port the server listens on
EXPOSE 6380

# 0.0.0.0 = accept connections from outside the container
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "6380", "--capacity", "1000"]

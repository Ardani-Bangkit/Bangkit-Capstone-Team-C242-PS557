# Gunakan Python sebagai base image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Copy semua file ke dalam image
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port untuk aplikasi
EXPOSE 8080

# Jalankan aplikasi
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]

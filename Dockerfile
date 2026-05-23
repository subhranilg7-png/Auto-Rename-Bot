FROM python:3.10-slim

# Install FFmpeg and mkvtoolnix
RUN apt update && \
    apt install -y ffmpeg mkvtoolnix && \
    apt clean

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "bot.py"]

# Dockerfile per Flask EAF -> CSV

# Base image
FROM python:3.12-slim

# Imposta la cartella di lavoro
WORKDIR /app

# Copia i file del progetto
COPY ./app /app

# Aggiorna pip, setuptools, wheel
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt

# Imposta DNS pubblico per evitare problemi di risoluzione
#RUN echo "nameserver 8.8.8.8" > /etc/resolv.conf

# Installa le dipendenze Python
RUN pip install Flask==2.3.3 pandas==2.1.1

# Espone la porta 5000 (Flask)
EXPOSE 5000

# Comando di avvio
CMD ["python", "app.py"]

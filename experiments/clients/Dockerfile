FROM python:3.9-slim-buster

COPY mqtt_opcua_client.py /app/mqtt_opcua_client.py
COPY requirements.txt /app/requirements.txt
COPY config.yaml /app/config.yaml

WORKDIR /app

RUN pip3 install -r requirements.txt

ENV PYTHONPATH "/app/"
ENV PYTHONUNBUFFERED 1

CMD [ "python3", "mqtt_opcua_client.py"]

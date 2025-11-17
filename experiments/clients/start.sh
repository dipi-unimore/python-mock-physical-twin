#!/bin/bash

docker run --name=mockpt-opcua-mqtt-client \
    --restart always \
    -v $(pwd)/config.yaml:/app/config.yaml \
    -d "registry.gitlab.com/dt-trustworthiness/physical-twin-emulator/mockpt-opcua-mqtt-client:0.2"
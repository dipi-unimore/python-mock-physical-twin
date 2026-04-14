#!/bin/bash

docker run --name=physical_twin_emulator \
    -p 5555:5555 \
    --restart always \
    -v $(pwd)/mqtt_simulation_config.yaml:/app/emulator_conf.yaml \
    -v $(pwd)/mqtt_use.yaml:/app/mqtt_use.yaml \
    -v $(pwd)/simulation.yaml:/app/simulation.yaml \
    -d registry.gitlab.com/dt-trustworthiness/physical-twin-emulator:0.2
#!/bin/bash

while true; do
    python -u /data/sso/mumble/authenticator/mumble-sso-auth.py | tee -a /var/log/mumble-sso-auth.log
    sleep 5
done

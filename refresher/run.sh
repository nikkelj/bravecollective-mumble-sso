#!/bin/bash

while true; do
    php /data/sso/mumble/refresher/mumble-sso-runner.php | tee -a /var/log/mumble-sso-runner.log
    sleep 5
done

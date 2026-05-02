#!/bin/bash
#


rsync -avz  ./ tomme@pa.protection-now.com:~/agents/signal-bot/
#rsync -avz --exclude 'node_modules' --exclude 'app/backend/.env' ./app/ evroc-user@194.14.80.135:~/guest-card-system/

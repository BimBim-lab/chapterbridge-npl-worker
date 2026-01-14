#!/bin/bash
# Auto-restart worker loop
# Automatically restarts worker if it exits (graceful or crash)
# Usage: nohup bash start_worker_loop.sh &

WORKER_DIR="/workspace/chapterbridge-npl-worker"
LOG_FILE="/workspace/worker.log"
RESTART_LOG="/workspace/worker_restarts.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$RESTART_LOG"
}

cd "$WORKER_DIR" || exit 1

log "=========================================="
log "Worker Auto-Restart Loop Started"
log "=========================================="

# Load environment variables
export $(cat .env | grep -v '^#' | grep -v '^$' | xargs)

RESTART_COUNT=0

while true; do
    RESTART_COUNT=$((RESTART_COUNT + 1))
    log "Starting worker (restart #${RESTART_COUNT})..."
    
    # Run worker (blocks until exit)
    python3 -m nlp_worker.main >> "$LOG_FILE" 2>&1
    EXIT_CODE=$?
    
    log "Worker exited with code $EXIT_CODE"
    
    # Exit code 0 = graceful shutdown (max jobs reached)
    # Exit code != 0 = crash/error
    
    if [ $EXIT_CODE -eq 0 ]; then
        log "Graceful shutdown detected (likely reached max jobs), restarting in 5 seconds..."
        sleep 5
    else
        log "Unexpected exit (crash?), restarting in 10 seconds..."
        sleep 10
    fi
    
    # Pull latest code before restart (optional)
    # git pull origin main
done

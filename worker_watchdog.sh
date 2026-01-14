#!/bin/bash
# Worker Watchdog Script
# Auto-restart worker if stuck or crashed
# Usage: nohup bash worker_watchdog.sh &

WORKER_DIR="/workspace/chapterbridge-npl-worker"
LOG_FILE="/workspace/worker.log"
WATCHDOG_LOG="/workspace/watchdog.log"
CHECK_INTERVAL=300  # Check every 5 minutes
STUCK_THRESHOLD=600  # Consider stuck if no progress in 10 minutes

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$WATCHDOG_LOG"
}

get_last_log_time() {
    # Get timestamp of last "Job.*completed" line in log
    tail -100 "$LOG_FILE" 2>/dev/null | grep "Job.*completed" | tail -1 | awk '{print $1, $2}' || echo ""
}

get_worker_pid() {
    ps aux | grep 'python3 -m nlp_worker.main' | grep -v grep | awk '{print $2}'
}

start_worker() {
    log "Starting worker..."
    cd "$WORKER_DIR" || exit 1
    export $(cat .env | grep -v '^#' | grep -v '^$' | xargs)
    nohup python3 -m nlp_worker.main > "$LOG_FILE" 2>&1 &
    sleep 5
    PID=$(get_worker_pid)
    if [ -n "$PID" ]; then
        log "Worker started with PID: $PID"
        return 0
    else
        log "ERROR: Failed to start worker"
        return 1
    fi
}

log "=========================================="
log "Worker Watchdog Started"
log "Check interval: ${CHECK_INTERVAL}s"
log "Stuck threshold: ${STUCK_THRESHOLD}s"
log "=========================================="

LAST_PROGRESS_TIME=$(date +%s)

while true; do
    sleep "$CHECK_INTERVAL"
    
    PID=$(get_worker_pid)
    CURRENT_TIME=$(date +%s)
    
    if [ -z "$PID" ]; then
        log "WARNING: Worker process not found, restarting..."
        start_worker
        LAST_PROGRESS_TIME=$(date +%s)
        continue
    fi
    
    # Check if worker is making progress
    LAST_LOG=$(get_last_log_time)
    
    if [ -n "$LAST_LOG" ]; then
        # Calculate time since last completed job
        LAST_LOG_TIMESTAMP=$(date -d "$LAST_LOG" +%s 2>/dev/null || echo "0")
        
        if [ "$LAST_LOG_TIMESTAMP" -gt 0 ]; then
            TIME_SINCE_PROGRESS=$((CURRENT_TIME - LAST_LOG_TIMESTAMP))
            
            if [ "$TIME_SINCE_PROGRESS" -gt "$STUCK_THRESHOLD" ]; then
                log "WARNING: Worker stuck (no progress for ${TIME_SINCE_PROGRESS}s), restarting..."
                pkill -f 'python3 -m nlp_worker.main'
                sleep 5
                start_worker
                LAST_PROGRESS_TIME=$(date +%s)
            else
                log "Worker healthy (last progress ${TIME_SINCE_PROGRESS}s ago, PID: $PID)"
                LAST_PROGRESS_TIME="$LAST_LOG_TIMESTAMP"
            fi
        fi
    fi
    
    # Check memory usage
    MEM_PERCENT=$(ps aux | grep "python3 -m nlp_worker" | grep -v grep | awk '{print $4}' | head -1)
    if [ -n "$MEM_PERCENT" ]; then
        # Convert to integer for comparison
        MEM_INT=$(echo "$MEM_PERCENT" | cut -d. -f1)
        if [ "$MEM_INT" -gt 80 ]; then
            log "WARNING: High memory usage (${MEM_PERCENT}%), consider restarting"
        fi
    fi
done

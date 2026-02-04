#!/bin/bash
set -euo pipefail

# Backup script for nx-backend databases
# Runs daily via cron at 4 AM

ENV_FILE=/opt/nx-backend/.env.prod

# Load environment variables
if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
else
  echo "$(date): Missing env file $ENV_FILE" >> /var/log/nx-backup.log
  exit 1
fi

BACKUP_DIR="/opt/nx-backups"
DATE=$(date +"%Y-%m-%d_%H-%M-%S")
LOGFILE="/var/log/nx-backup.log"

log() { echo "$(date): $1" | tee -a "$LOGFILE"; }

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Use temp dir, only move on success
TEMP_DEST=$(mktemp -d)
DEST="$BACKUP_DIR/$DATE"

log "Starting backup to temp: $TEMP_DEST"

cleanup() { rm -rf "$TEMP_DEST"; }
trap cleanup EXIT

# PostgreSQL backup
log "Dumping PostgreSQL..."
if docker exec nx-backend-db-1 pg_dumpall -U "${POSTGRES_USER}" --clean --if-exists 2>/dev/null | gzip > "$TEMP_DEST/postgres_all.sql.gz"; then
  PG_SIZE=$(du -h "$TEMP_DEST/postgres_all.sql.gz" | cut -f1)
  if [ "$(stat -c%s "$TEMP_DEST/postgres_all.sql.gz")" -gt 1000 ]; then
    log "PostgreSQL backup complete: $PG_SIZE"
  else
    log "PostgreSQL backup too small, likely failed"
    exit 1
  fi
else
  log "PostgreSQL backup FAILED"
  exit 1
fi

# MongoDB backup
log "Dumping MongoDB..."
if docker exec nx-backend-mongodb-1 mongodump --archive --gzip \
  -u "$MONGODB_USERNAME" -p "$MONGODB_PASSWORD" --authenticationDatabase admin \
  2>/dev/null > "$TEMP_DEST/mongodb.archive.gz"; then
  MONGO_SIZE=$(du -h "$TEMP_DEST/mongodb.archive.gz" | cut -f1)
  if [ "$(stat -c%s "$TEMP_DEST/mongodb.archive.gz")" -gt 1000 ]; then
    log "MongoDB backup complete: $MONGO_SIZE"
  else
    log "MongoDB backup too small, likely failed"
    exit 1
  fi
else
  log "MongoDB backup FAILED"
  exit 1
fi

# All succeeded - move to final destination
mkdir -p "$DEST"
mv "$TEMP_DEST"/* "$DEST/"
trap - EXIT  # Disable cleanup since we moved files

# Cleanup old backups (keep last 7 days)
find "$BACKUP_DIR" -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \; 2>/dev/null || true
log "Cleaned up backups older than 7 days"

log "Backup complete: $DEST (PG: $PG_SIZE, Mongo: $MONGO_SIZE)"
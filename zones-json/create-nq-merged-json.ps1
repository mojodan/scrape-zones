# Build date strings for file names
$date      = Get-Date
#$date      = Get-Date -Day 21 -Month 6 -Year 2026
$YYYYMMDD  = $date.ToString("yyyyMMdd")
$YYMMDD    = $date.ToString("yyMMdd")


# Parse worksheet PDF to markdown/JSON
lit parse "C:\EminiPlayer\es_worksheets\${YYYYMMDD}NQ-X30.pdf" --format json -o "C:\EminiPlayer\es_zones_json\$YYYYMMDD-nq.md"
#lit parse "C:\EminiPlayer\es_worksheets\${YYYYMMDD}NQ-X77.pdf" --format json -o "C:\EminiPlayer\es_zones_json\$YYYYMMDD-nq.md"

# Convert markdown to structured JSON
node ..\parse-zones.mjs -o "C:\EminiPlayer\es_zones_json" "C:\EminiPlayer\es_zones_json\$YYYYMMDD-nq.md"

# Merge zone text file with parsed JSON
node ..\merge.mjs -zone "C:\EminiPlayer\es_zones\NQ_ZONES_1$YYMMDD.txt" -json "C:\EminiPlayer\es_zones_json\$YYYYMMDD-nq.json" -output "C:\EminiPlayer\es_merge_zones\NQ_ZONES_1$YYMMDD.txt"

# Move original zones file to backup folder
Move-Item -Force -Path "C:\EminiPlayer\es_zones\NQ_ZONES_1$YYMMDD.txt" -Destination "C:\EminiPlayer\es_zones\original-zones\"

# Move merged  zones file to es_zones folder
Move-Item -Force -Path "C:\EminiPlayer\es_merge_zones\NQ_ZONES_1$YYMMDD.txt" -Destination "C:\EminiPlayer\es_zones\"


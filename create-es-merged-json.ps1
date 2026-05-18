# Build date strings for file names
$date      = Get-Date
$YYYYMMDD  = $date.ToString("yyyyMMdd")
$YYMMDD    = $date.ToString("yyMMdd")

# Move original zones file to backup folder
Move-Item -Path "C:\EminiPlayer\ES_ZONES_1$YYMMDD.txt" -Destination "C:\EminiPlayer\original-zones\"

# Parse worksheet PDF to markdown/JSON
lit parse "C:\EminiPlayer\es_worksheets\${YYYYMMDD}TW-X72.pdf" --format json -o "C:\EminiPlayer\es_zones_json\$YYYYMMDD-es.md"

# Convert markdown to structured JSON
node ..\parse-zones.mjs -o "C:\EminiPlayer\es_zones_json" "C:\EminiPlayer\es_zones_json\$YYYYMMDD-es.md"

# Merge zone text file with parsed JSON
node ..\merge.mjs -zone "C:\EminiPlayer\es_zones\ES_ZONES_1$YYMMDD.txt" -json "C:\EminiPlayer\es_zones_json\$YYYYMMDD-es.json" -output "C:\EminiPlayer\es_merge_zones\ES_ZONES_1$YYMMDD.txt"

#!/bin/bash

# URLs of the images
URLS=("https://mausam.imd.gov.in/Satellite/3Dasiasec_ir1.jpg" "https://mausam.imd.gov.in/Satellite/3Dasiasec_ctbt.jpg")

# Get the current UTC date and time
DATE=$(date -u +%Y%m%d)
TIME=$(date -u +%H%M)

# Directory name based on the current UTC date
DIR="/etc/myData/sat-image/$DATE"

# Create the directory if it doesn't exist
mkdir -p "$DIR"

# Function to download and process images
download_images() {
    # Download and process each image
    for URL in "${URLS[@]}"; do
	# Get the base name of the image
	BASENAME=$(basename "$URL")
	# New name with the date and time
	NEWNAME="${BASENAME%.*}-$DATE-$TIME.${BASENAME##*.}"

	# Download the image
	wget -q -O "$NEWNAME" "$URL"

	# Compare the image with the last one in the directory
	LASTFILE=$(ls -t "$DIR/${BASENAME%.*}*.${BASENAME##*.}" 2>/dev/null | head -1)
	if [ -n "$LASTFILE" ]; then
	    if cmp -s "$NEWNAME" "$LASTFILE"; then
		# Images are the same, delete the new one
		rm "$NEWNAME"
	    else
		# Images are different, move the new one to the directory
		mv "$NEWNAME" "$DIR/"
	    fi
	else
	    # No previous file exists, move the new one to the directory
	    mv "$NEWNAME" "$DIR/"
	fi
    done
}

# Infinite loop to run the script every 10 minutes
while true; do
    download_images
    sleep 600
done

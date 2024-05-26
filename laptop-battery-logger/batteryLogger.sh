#!/bin/sh

lastLevel=0

while true
do
    battery_level=`acpi -b | grep -P -o '[0-9]+(?=%)'`
    if [ $lastLevel -eq $battery_level ]
    then
	continue
    fi
    lastLevel=$battery_level
    utctime=`date -u +%Y%m%d-%H%M%S`
    filename="/etc/myData/batData/batLog-"`date -u +%Y%m%d`.txt
    echo $utctime $battery_level >> $filename
    sleep 10
done

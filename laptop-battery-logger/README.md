a script to log battery level
* it checks in each 10 seconds
* if level changed, then it logs in a file
* a file is created in each day

if you want to run the script at the starting of the computer, then
* place the script in a location `/etc/myData/`
* create a file `/etc/rc.local`
* content of the file should be like this
  ```
  #!/bin/sh
  /etc/myData/batteryLogger.sh &
  /etc/myData/download-sat-image.sh &
  exit 0
  ```

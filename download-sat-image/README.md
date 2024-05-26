a script to download a series of jpg image and keep it in a folder. the criteria is as follows.

* first create a directory with utc date (i.e. sat-image-20240526), if does not exists
* here is the url to the image https://mausam.imd.gov.in/Satellite/3Dasiasec_ir1.jpg, https://mausam.imd.gov.in/Satellite/3Dasiasec_ctbt.jpg
* for each link, download the image. rename it by adding "-20240526-1435" before file extention (utc date and time)
* now compare it with the last similar photo in the directory.
* if same then delete and skip, otherwise move the photo to directory.
* sleep for 10 minutes before checking again

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

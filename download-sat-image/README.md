a script to download a series of jpg image and keep it in a folder. the criteria is as follows.
1. first create a directory with utc date (i.e. sat-image-20240526), if does not exists
2. here is the url to the image https://mausam.imd.gov.in/Satellite/3Dasiasec_ir1.jpg, https://mausam.imd.gov.in/Satellite/3Dasiasec_ctbt.jpg
3. for each link, download the image. rename it by adding "-20240526-1435" before file extention (utc date and time)
4. now compare it with the last similar photo in the directory.
5. if same then delete and skip, otherwise move the photo to directory.
6. sleep for 10 minutes before checking again
